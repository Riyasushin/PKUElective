import base64
from io import BytesIO
import json

import requests
from PIL import Image

from .captcha_util import Captcha
from ..config import BaseConfig
from .._internal import get_abs_path
from ..exceptions import OperationFailedError, OperationTimeoutError, RecognizerError


class APIConfig(object):
    _DEFAULT_CONFIG_PATH = '../apikey.json'

    def __init__(self, path=_DEFAULT_CONFIG_PATH):
        with open(get_abs_path(path), 'r') as handle:
            self._apikey = json.load(handle)
        for key in ('username', 'password', 'RecognitionTypeid', 'Timeout'):
            if key not in self._apikey or not str(self._apikey[key]).strip():
                raise ValueError('Missing apikey.json field: %s' % key)
        if self.timeout <= 0:
            raise ValueError('apikey.json Timeout must be positive')
        self.typeid

    @property
    def uname(self):
        return self._apikey['username']

    @property
    def pwd(self):
        return self._apikey['password']

    @property
    def typeid(self):
        return int(self._apikey['RecognitionTypeid'])

    @property
    def timeout(self):
        return int(self._apikey['Timeout'])


class TTShituRecognizer(object):
    _RECOGNIZER_URL = "https://api.ttshitu.com/base64"

    def __init__(self):
        self._config = APIConfig()

    def recognize(self, raw):
        _typeid_ = self._config.typeid
        encode = self.to_b64(raw)
        data = {
            "username": self._config.uname,
            "password": self._config.pwd,
            "image": encode,
            "typeid": _typeid_
        }
        try:
            response = requests.post(self._RECOGNIZER_URL, json=data, timeout=self._config.timeout)
            response.raise_for_status()
            result = response.json()
        except requests.Timeout:
            raise OperationTimeoutError(msg="Recognizer connection time out")
        except requests.ConnectionError:
            raise OperationFailedError(msg="Unable to coonnect to the recognizer")
        except (requests.RequestException, ValueError):
            raise RecognizerError(msg="Recognizer returned an invalid response") from None

        if not isinstance(result, dict) or result.get('success') is not True:
            reason = str(result.get('message', 'unrecognized response')) if isinstance(result, dict) else 'unrecognized response'
            for secret in (self._config.uname, self._config.pwd):
                if isinstance(secret, str) and secret:
                    reason = reason.replace(secret, '[redacted]')
            raise RecognizerError(msg='Recognizer rejected request: %s' % reason[:200])
        payload = result.get('data')
        code = payload.get('result') if isinstance(payload, dict) else None
        if not isinstance(code, str) or not code.strip():
            raise RecognizerError(msg="Recognizer returned no code")
        return Captcha(code.strip(), None, None, None, None)

    @staticmethod
    def to_b64(raw):
        im = Image.open(BytesIO(raw))
        try:
            if im.is_animated:
                oim = im
                oim.seek(oim.n_frames - 1)
                im = Image.new('RGB', oim.size)
                im.paste(oim)
        except AttributeError:
            pass
        buffer = BytesIO()
        im.convert('RGB').save(buffer, format='JPEG')
        b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return b64
