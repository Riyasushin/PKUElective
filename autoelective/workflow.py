"""Bounded single-course run: login, inspect, validate, submit once, verify.

The read-only mode never initializes a recognizer. Submission responses, even
success messages, must be checked against the selected-course state table.
"""
from .parser import (get_tables, get_table_header, get_courses_with_detail,
                     get_election_states, get_sida)
from .exceptions import ElectionSuccess, ElectionRepeatedError, OperationFailedError


def snapshot(client, config):
    r = client.get_SupplyCancel(config.iaaa_id)
    if config.supply_cancel_page != 1:
        r = client.get_supplement(config.iaaa_id, page=config.supply_cancel_page)
    tables = get_tables(r._tree)
    plans = [t for t in tables if '补选' in get_table_header(t)]
    elected = [t for t in tables if '选课状态' in get_table_header(t)]
    if len(plans) != 1 or len(elected) != 1:
        raise OperationFailedError(msg='Cannot identify course tables')
    return get_courses_with_detail(plans[0]), get_election_states(elected[0])


def validate_captcha(client, username, recognizer, attempts=3, emit=print):
    if attempts < 1:
        raise ValueError('Captcha attempts must be positive')
    for attempt in range(1, attempts + 1):
        raw = client.get_DrawServlet().content
        captcha = recognizer.recognize(raw)
        response = client.get_Validate(username, captcha.code)
        try:
            status = str(response.json()['valid'])
        except (ValueError, KeyError, TypeError):
            raise OperationFailedError(msg='Invalid captcha validation response') from None
        emit('Captcha validation attempt %d: %s' % (attempt, status))
        if status == '2':
            return
        if status != '0':
            raise OperationFailedError(msg='Unknown captcha validation status')
    raise OperationFailedError(msg='Captcha attempt limit reached')


def run_once(config, *, submit=False, attempts=3, client=None, auth=None,
             recognizer_factory=None, emit=print):
    courses = config.courses
    if len(courses) != 1:
        raise ValueError('--once/--check requires exactly one configured course')
    config.check_supply_cancel_page(config.supply_cancel_page)
    cid, target = next(iter(courses.items()))
    if client is None:
        from .elective import ElectiveClient
        client = ElectiveClient(1, timeout=config.elective_client_timeout)
    if auth is None:
        from .iaaa import IAAAClient
        auth = IAAAClient(timeout=config.iaaa_client_timeout)
    auth.oauth_home()
    token = auth.oauth_login(config.iaaa_id, config.iaaa_password).json()['token']
    response = client.sso_login(token)
    if config.is_dual_degree:
        client.sso_login_dual_degree(get_sida(response), config.identity, response.url)
    emit('IAAA and elective login completed')
    plans, states = snapshot(client, config)
    if target in states:
        emit('Target state: %s' % states[target])
        return 'already_elected' if states[target] == '已选上' else 'pending'
    matches = [course for course in plans if course == target]
    if not matches:
        raise OperationFailedError(msg='Target absent from configured page; check page number')
    course = matches[0]
    emit('Target: %s; page=%d; quota=%s' % (target.name, config.supply_cancel_page, course.status))
    if not submit:
        return 'available' if course.is_available() else 'full'
    if not course.is_available():
        return 'full'
    for delay in config.delays.values():
        if delay.cid == cid and course.remaining_quota > delay.threshold:
            return 'delayed'
    if not course.href:
        raise OperationFailedError(msg='Target has no submission link')
    if recognizer_factory is None:
        from .captcha.proxy import RecognitionProxy
        recognizer_factory = RecognitionProxy
    validate_captcha(client, config.iaaa_id, recognizer_factory(), attempts, emit)
    emit('Submitting target once')
    try:
        client.get_ElectSupplement(course.href)
    except (ElectionSuccess, ElectionRepeatedError):
        pass  # A message alone is not proof of enrollment.
    except Exception as exc:
        # A timeout may happen after the server commits the enrollment.
        # Reconcile via a read, never replay the submission here.
        emit('Submission response: %s; checking selected-course state' % type(exc).__name__)
        _, states = snapshot(client, config)
        if states.get(target) == '已选上':
            return 'elected'
        raise
    _, states = snapshot(client, config)
    state = states.get(target)
    emit('Verified target state: %s' % (state or 'absent'))
    if state == '已选上':
        return 'elected'
    if state:
        return 'pending'
    raise OperationFailedError(msg='Submission not confirmed in selected-course table')
