def test_create_patient(client, auth_headers):
    response = client.post(
        "/api/v1/patients/",
        json={
            "dni": "30123456",
            "first_name": "Ana",
            "last_name": "Perez",
            "email": "ana@example.com",
            "phone": "+5491111111111",
            "observations": "Paciente nueva",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["dni"] == "30123456"
    assert data["first_name"] == "Ana"
    assert data["email"] == "ana@example.com"
    assert data["is_active"] is True
