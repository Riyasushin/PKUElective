"""Configured single-request recognition, without state shared between images.

Returns Captcha, honoring RecognitionTypeid and Timeout in apikey.json.
"""
from .online import TTShituRecognizer


class RecognitionProxy(TTShituRecognizer):
    pass
