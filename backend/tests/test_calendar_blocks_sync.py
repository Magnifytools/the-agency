"""Conciliación de bloques de trabajo con Google Calendar (sin red)."""
from datetime import date, datetime, timedelta

from backend.services.calendar_blocks_sync import (
    BLOCK_PROPERTY, BlockState, EventState, _event_body, _event_state, plan_sync, window,
)

SYNCED = datetime(2026, 10, 28, 9, 0, 0)
START, END = datetime(2026, 10, 29, 10, 0), datetime(2026, 10, 29, 11, 30)


def block(**changes) -> BlockState:
    values = dict(
        id=7, starts_at=START, ends_at=END, updated_at=SYNCED, google_event_id="ev7",
        google_event_updated="2026-10-28T09:00:00.000Z", google_synced_at=SYNCED,
        summary="Auditoría · Fit", description="Bloque",
    )
    return BlockState(**{**values, **changes})


def event(**changes) -> EventState:
    values = dict(
        id="ev7", block_id=7, cancelled=False, updated="2026-10-28T09:00:00.000Z",
        starts_at=START, ends_at=END, summary="Auditoría · Fit", description="Bloque",
    )
    return EventState(**{**values, **changes})


def test_sin_cambios_no_hace_nada():
    plan = plan_sync([block()], [event()])
    assert (plan.create, plan.patch, plan.from_google, plan.delete_blocks, plan.delete_events) == ([], [], [], [], [])


def test_bloque_nuevo_crea_su_evento():
    nuevo = block(google_event_id=None, google_event_updated=None, google_synced_at=None)
    assert plan_sync([nuevo], []).create == [nuevo]


def test_evento_creado_sin_guardar_se_reconoce_por_su_marca():
    nuevo = block(google_event_id=None, google_event_updated=None, google_synced_at=None)
    plan = plan_sync([nuevo], [event()])
    assert plan.create == [] and plan.patch == [(nuevo, "ev7")]


def test_cambio_en_la_app_actualiza_el_evento():
    movido = block(starts_at=START + timedelta(hours=1), ends_at=END + timedelta(hours=1),
                   updated_at=SYNCED + timedelta(minutes=5))
    assert plan_sync([movido], [event()]).patch == [(movido, "ev7")]


def test_cambio_de_titulo_de_la_tarea_actualiza_el_evento():
    renombrado = block(summary="Auditoría técnica · Fit")
    assert plan_sync([renombrado], [event()]).patch == [(renombrado, "ev7")]


def test_cambio_en_google_mueve_el_bloque():
    movido = event(updated="2026-10-28T10:00:00.000Z", starts_at=START + timedelta(hours=2), ends_at=END + timedelta(hours=2))
    assert plan_sync([block()], [movido]).from_google == [(block(), movido)]


def test_los_dos_cambian_y_gana_el_ultimo():
    en_la_app = block(starts_at=START + timedelta(hours=1), ends_at=END + timedelta(hours=1),
                      updated_at=datetime(2026, 10, 28, 10, 30))
    antes_en_google = event(updated="2026-10-28T10:00:00.000Z", starts_at=START + timedelta(hours=3), ends_at=END + timedelta(hours=3))
    assert plan_sync([en_la_app], [antes_en_google]).patch == [(en_la_app, "ev7")]
    despues_en_google = event(updated="2026-10-28T11:00:00.000Z", starts_at=START + timedelta(hours=3), ends_at=END + timedelta(hours=3))
    assert plan_sync([en_la_app], [despues_en_google]).from_google == [(en_la_app, despues_en_google)]


def test_cambio_en_google_que_un_bloque_no_admite_se_deshace():
    for raro in (
        event(updated="2026-10-28T10:00:00.000Z", ends_at=START + timedelta(hours=13)),  # > 12 h
        event(updated="2026-10-28T10:00:00.000Z", ends_at=datetime(2026, 10, 30, 9, 0)),  # otro día
        event(updated="2026-10-28T10:00:00.000Z", starts_at=None, ends_at=None),  # todo el día
    ):
        assert plan_sync([block()], [raro]).patch == [(block(), "ev7")]


def test_terminar_a_medianoche_es_el_mismo_dia():
    hasta_medianoche = event(updated="2026-10-28T10:00:00.000Z", starts_at=datetime(2026, 10, 29, 22, 0),
                             ends_at=datetime(2026, 10, 30, 0, 0))
    assert plan_sync([block()], [hasta_medianoche]).from_google


def test_evento_borrado_en_google_borra_el_bloque():
    assert plan_sync([block()], [event(cancelled=True)]).delete_blocks == [block()]
    assert plan_sync([block()], []).delete_blocks == [block()]


def test_bloque_recuperado_con_deshacer_vuelve_a_crear_su_evento():
    recuperado = block(updated_at=SYNCED + timedelta(hours=1))
    plan = plan_sync([recuperado], [event(cancelled=True)])
    assert plan.create == [recuperado] and plan.delete_blocks == []


def test_bloque_borrado_en_la_app_borra_su_evento():
    assert plan_sync([], [event()]).delete_events == ["ev7"]


def test_eventos_sin_marca_no_se_tocan():
    plan = plan_sync([], [event(id="ajeno", block_id=None)])
    assert plan.delete_events == []


def test_ventana_del_lunes_de_esta_semana_y_cinco_semanas():
    start, end = window(date(2026, 10, 29))  # jueves
    assert start == datetime(2026, 10, 26) and end == datetime(2026, 11, 30)


def test_el_evento_lleva_la_marca_y_la_hora_de_la_agencia():
    body = _event_body(block())
    assert body["extendedProperties"]["private"][BLOCK_PROPERTY] == "7"
    assert body["start"] == {"dateTime": "2026-10-29T10:00:00", "timeZone": "Europe/Madrid"}


def test_lectura_del_evento_de_google():
    state = _event_state({
        "id": "ev7", "status": "confirmed", "updated": "2026-10-28T09:00:00.000Z",
        "start": {"dateTime": "2026-10-29T09:00:00Z"}, "end": {"dateTime": "2026-10-29T10:30:00+00:00"},
        "extendedProperties": {"private": {BLOCK_PROPERTY: "7"}},
    })
    assert (state.block_id, state.starts_at, state.ends_at) == (7, START, END)
    ajeno = _event_state({"id": "x", "start": {"date": "2026-10-29"}, "end": {"date": "2026-10-30"}})
    assert ajeno.block_id is None and ajeno.starts_at is None
