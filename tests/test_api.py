"""API tests: the whole stack through HTTP, including status codes."""


def codes(response) -> list[str]:
    return [i["code"] for i in response.json()["detail"]]


def test_root(client):
    assert client.get("/").json() == {"message": "InvoiceFlow API"}


def test_create_valid_invoice(client, invoice_payload):
    response = client.post("/invoices", json=invoice_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["status"] == "VALID"
    # Phase 3: amounts serialize as strings, because JSON has no decimal type
    assert body["subtotal"] == "1000.00"


def test_invalid_total(client, invoice_payload):
    response = client.post(
        "/invoices", json=invoice_payload(subtotal="1000", tax="190", total="1300")
    )
    assert response.status_code == 422
    assert codes(response) == ["TOTAL_MISMATCH"]


def test_future_date(client, invoice_payload):
    response = client.post("/invoices", json=invoice_payload(invoice_date="2099-12-31"))
    assert response.status_code == 422
    assert codes(response) == ["FUTURE_INVOICE_DATE"]


def test_unsupported_currency(client, invoice_payload):
    response = client.post("/invoices", json=invoice_payload(currency="XYZ"))
    assert response.status_code == 422
    assert codes(response) == ["INVALID_CURRENCY"]


def test_duplicate_invoice_returns_409(client, invoice_payload):
    payload = invoice_payload(invoice_number="API-DUP")
    assert client.post("/invoices", json=payload).status_code == 201

    response = client.post("/invoices", json=payload)
    assert response.status_code == 409
    assert codes(response) == ["DUPLICATE_INVOICE"]


def test_validation_beats_duplicate(client, invoice_payload):
    """Phase 12: malformed and duplicate together is a 422, not a 409."""
    client.post("/invoices", json=invoice_payload(invoice_number="API-BOTH"))

    response = client.post(
        "/invoices", json=invoice_payload(invoice_number="API-BOTH", currency="XYZ")
    )
    assert response.status_code == 422
    assert codes(response) == ["INVALID_CURRENCY"]


def test_not_found(client):
    response = client.get("/invoices/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Invoice not found"}


def test_list_invoices(client, invoice_payload):
    before = len(client.get("/invoices").json())
    client.post("/invoices", json=invoice_payload(invoice_number="LIST-1"))
    client.post("/invoices", json=invoice_payload(invoice_number="LIST-2"))

    listed = client.get("/invoices").json()
    assert len(listed) == before + 2
    assert [i["id"] for i in listed] == sorted(i["id"] for i in listed)


def test_get_invoice_by_id(client, invoice_payload):
    created = client.post("/invoices", json=invoice_payload(invoice_number="GET-1"))
    invoice_id = created.json()["id"]

    fetched = client.get(f"/invoices/{invoice_id}")
    assert fetched.status_code == 200
    assert fetched.json()["invoice_number"] == "GET-1"


def test_schema_validation_is_separate_from_business_rules(client):
    """Phase 4: two kinds of 422, told apart by which keys the body has."""
    response = client.post("/invoices", json={"nonsense": True})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert len(detail) == 7  # one per missing required field
    assert set(detail[0]) == {"type", "loc", "msg", "input"}  # Pydantic's shape


def test_non_integer_path_parameter(client):
    assert client.get("/invoices/abc").status_code == 422


def test_amount_out_of_range_is_422_not_500(client, invoice_payload):
    """Phase 12 closed this; before then it escaped as a bare 500."""
    response = client.post(
        "/invoices",
        json=invoice_payload(
            invoice_number="BIG",
            subtotal="99999999999.00", tax="1.00", total="100000000000.00",
        ),
    )
    assert response.status_code == 422
    assert codes(response) == ["AMOUNT_OUT_OF_RANGE"]


def test_amounts_sent_as_strings_keep_their_scale(client, invoice_payload):
    """Phase 3: a JSON number becomes a float first and loses scale."""
    response = client.post(
        "/invoices",
        json=invoice_payload(
            invoice_number="SCALE", subtotal="0.10", tax="0.20", total="0.30"
        ),
    )
    assert response.json()["tax"] == "0.20"
