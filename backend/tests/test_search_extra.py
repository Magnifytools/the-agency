"""La búsqueda global también devuelve resúmenes y notas por aclarar."""


async def test_la_busqueda_trae_resumenes_y_notas(admin_client):
    res = await admin_client.get("/api/search", params={"q": "sage"})
    assert res.status_code == 200
    body = res.json()
    assert body["digests"] == [] and body["notes"] == []


async def test_sin_permiso_de_resumenes_no_los_busca(member_client):
    # El miembro de los tests sólo lee clientes.
    body = (await member_client.get("/api/search", params={"q": "sage"})).json()
    assert body["digests"] == [] and body["notes"] == []
