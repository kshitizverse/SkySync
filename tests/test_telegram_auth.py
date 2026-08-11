import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main


def test_send_code_rejects_invalid_phone_format():
    client = main.app.test_client()
    response = client.post('/api/auth/send-code', json={'phone': '12345'})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['success'] is False


def test_verify_code_requires_session():
    client = main.app.test_client()
    response = client.post('/api/auth/verify-code', json={'phone_code': '123456'})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['success'] is False
