-- 004 — Guardar las fotos de la página, para poder comparar el ANTES.
--
-- Vigil sabía decir que el HTML cambió y enseñar las líneas. Lo que no sabía
-- decir es cómo se ve: un bloque que se desplaza 200 px no se lee en un diff de
-- etiquetas, y es lo primero que se quiere ver al abrir la ficha de un cambio.
--
-- Las fotos se sacan A DEMANDA, nunca en el barrido (un Chromium por URL y por
-- noche alargaría el barrido de minutos a horas), pero comparar exige tener la
-- anterior guardada. De ahí esta tabla: cada vez que alguien pulsa el botón, la
-- foto se queda, y la siguiente ya tiene con qué compararse.
--
-- El PNG va en BLOB dentro del propio fichero, por la misma razón que los
-- cuerpos HTML (regla 8): el volumen de Railway es uno y el backup nocturno
-- copia la DB entera. Un directorio de imágenes al lado sería un segundo sitio
-- que respaldar y que se desincroniza.
create table if not exists page_shots (
    id          text primary key,
    watch_id    text not null references watches(id)  on delete cascade,
    client_id   text not null references clients(id)  on delete cascade,
    taken_at    text not null,
    taken_by    text references users(id) on delete set null,
    width       integer not null,
    height      integer not null,
    byte_size   integer not null,
    png         blob not null
);

-- La consulta es siempre "las últimas fotos de esta URL": el índice va por
-- watch y por fecha descendente.
create index if not exists idx_page_shots_watch
    on page_shots (watch_id, taken_at desc);
