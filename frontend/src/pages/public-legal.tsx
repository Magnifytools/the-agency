import type { ReactNode } from "react"
import { Link } from "react-router-dom"

/**
 * Páginas públicas sin login (/acerca y /privacidad) para la verificación de
 * Google OAuth: Google exige una página de inicio que describa la app y una
 * política que explique qué datos de Google lee y qué hace con ellos.
 * No se indexan (meta aquí + X-Robots-Tag en backend/main.py).
 *
 * Lo que cuentan debe coincidir con el código: gsc_service, gsc_detail_service,
 * ga4_service, google_calendar_service, calendar_blocks_sync y sus rutas. Si cambia qué se guarda, se cambia aquí.
 */

const CONTACT = "david@magnify.ing"
const UPDATED = "28 de octubre de 2026"

function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <title>{`${title} · The Agency`}</title>
      <meta name="robots" content="noindex, nofollow, noarchive" />
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-4 py-4">
          <Link to="/acerca" className="text-lg font-bold tracking-tight">
            The Agency<span className="text-brand">.</span>
          </Link>
          <nav className="flex gap-4 text-sm text-muted-foreground">
            <Link to="/acerca" className="hover:text-foreground">Qué es</Link>
            <Link to="/privacidad" className="hover:text-foreground">Privacidad</Link>
            <Link to="/login" className="hover:text-foreground">Entrar</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-10 text-sm leading-relaxed [&_h2]:mt-8 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_a]:underline">
        {children}
      </main>
      <footer className="border-t border-border">
        <p className="mx-auto max-w-3xl px-4 py-6 text-xs text-muted-foreground">
          The Agency es una herramienta de <a href="https://magnify.ing" className="underline">Magnify</a>. Contacto: <a href={`mailto:${CONTACT}`} className="underline">{CONTACT}</a>
        </p>
      </footer>
    </div>
  )
}

export function AboutPage() {
  return (
    <LegalLayout title="Qué es The Agency">
      <h1 className="text-2xl font-bold">The Agency</h1>
      <p>
        The Agency (agency.magnifytools.com) es la herramienta con la que Magnify, consultora de SEO,
        gestiona su trabajo: clientes, proyectos, tareas, tiempo dedicado y los resúmenes que envía a
        cada cliente. La usan el equipo de Magnify y los colaboradores y clientes a los que invitamos;
        no hay registro abierto.
      </p>

      <h2>Qué hace con Google</h2>
      <ul>
        <li>
          <strong>Search Console</strong> (sólo lectura): importa cada día los clics, impresiones y posición
          media de las webs de nuestros clientes, y el detalle por búsqueda y página de los últimos 120 días
          (más un total mensual por búsqueda de hasta 16 meses), para seguir su tráfico y añadir un bloque de cifras al resumen mensual que reciben.
        </li>
        <li>
          <strong>Google Analytics</strong> (sólo lectura): importa cada día las visitas, las conversiones
          (eventos clave), la parte de las visitas que llega desde asistentes de IA y los leads por página de
          entrada y canal, con el mismo fin.
        </li>
        <li>
          <strong>Google Calendar</strong> (sólo lectura, opcional y personal): cada persona puede conectar
          su calendario para ver su próxima reunión y sus reuniones junto a sus bloques de trabajo en Mi agenda.
        </li>
        <li>
          <strong>Calendario «The Agency»</strong> (opcional y personal): quien lo active publica sus bloques
          de trabajo en un calendario aparte que la app crea en su cuenta, y puede moverlos o borrarlos desde
          Google.
        </li>
      </ul>
      <p>
        The Agency sólo escribe en Google en ese calendario «The Agency», y sólo si la persona lo activa:
        nunca modifica ni borra nada en sus otros calendarios ni en Search Console o Analytics. Aparte de eso,
        lo único que pide a Google es retirar su propio acceso cuando se desconecta una cuenta.
      </p>
      <p>
        Detalle completo en la <Link to="/privacidad">política de privacidad</Link>.
      </p>

      <h2 lang="en">In English</h2>
      <div lang="en" className="space-y-3">
        <p>
          The Agency is the operations tool of Magnify, an SEO consultancy. It is used by our team and by
          collaborators and clients we invite; there is no public sign-up. It reads Google Search Console
          (including per-query and per-page detail for the last 120 days and monthly per-query totals for
          up to 16 months) and Google Analytics data (including daily lead events per landing page and
          channel) (read-only) for our clients' websites to track their traffic and to add
          a block of figures to the monthly report each client receives. Each user may optionally connect
          their own Google Calendar (read-only) to see their next meeting and their meetings next to their work blocks,
          and may choose to publish their work blocks to a separate "The Agency" calendar that the app creates in
          their account. That calendar is the only thing the app ever writes to in Google; it never changes or
          deletes anything in other calendars, Search Console or Analytics. Otherwise, the only request it makes
          is to revoke its own access when an account is disconnected. See the <Link to="/privacidad">privacy policy</Link>.
        </p>
      </div>
    </LegalLayout>
  )
}

export function PrivacyPage() {
  return (
    <LegalLayout title="Privacidad">
      <h1 className="text-2xl font-bold">Política de privacidad de The Agency</h1>
      <p className="text-muted-foreground">Actualizada el {UPDATED}.</p>
      <p>
        Esta política cubre la aplicación The Agency (agency.magnifytools.com) de Magnify. Para el resto de
        servicios de Magnify rige la <a href="https://magnify.ing/politica-privacidad/">política general</a>.
        Responsable y contacto: Magnify, <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
      </p>

      <h2>Datos de Google que usamos</h2>
      <h3>Google Search Console (permiso webmasters.readonly)</h3>
      <p>
        Un administrador conecta una cuenta de Google con acceso a las webs de nuestros clientes. Guardamos
        el email de esa cuenta y su token de acceso cifrado. De cada web guardamos un total por día: clics,
        impresiones y posición media. Además, durante 120 días, guardamos esas mismas cifras por día para cada
        búsqueda (consulta) y cada página de la web, para ver qué búsquedas, páginas y secciones suben o bajan
        y separar el tráfico de marca. Pasados esos 120 días, de cada búsqueda sólo conservamos un total por
        mes (clics, impresiones y posición media), durante un máximo de 16 meses y mientras la web esté
        asociada a un cliente activo, para ver cómo evoluciona su posición. De algunas webs conservamos además
        totales mensuales por búsqueda anteriores a esos 16 meses, con los mismos datos de Search Console, que
        importamos una sola vez de nuestra herramienta anterior; se guardan mientras la web esté asociada a un
        cliente activo. Con cada resumen mensual guardamos además las búsquedas y páginas que más visitas
        trajeron ese mes, las búsquedas cerca de la primera página (hasta cinco de cada) y cuántas visitas
        llegaron con la marca y sin ella, para que el resumen entregado no cambie. Las consultas son las que
        Google ya muestra agregadas y anonimizadas en Search Console: no identifican a ninguna persona. No
        guardamos países ni dispositivos.
      </p>
      <h3>Google Analytics (permiso analytics.readonly)</h3>
      <p>
        Con las mismas cuentas, guardamos por propiedad y día: visitas (sesiones), conversiones (eventos
        clave) y las visitas y conversiones que llegan desde asistentes de IA. La fuente de cada visita sólo
        se usa para calcular esa parte; no se guarda. Además, por día, página de entrada y canal (búsqueda
        orgánica, de pago, redes sociales…), guardamos el número de eventos que cuentan como lead para ese
        cliente (los que configuramos en su ficha, como el envío de un formulario), ya agregados por Google,
        durante un máximo de 16 meses; de algunas propiedades incluyen días que importamos una sola vez de
        nuestra herramienta anterior. No guardamos datos de usuarios individuales.
      </p>
      <h3>Google Calendar (permiso calendar.readonly)</h3>
      <p>
        Cada persona puede conectar su propio calendario. Leemos el título, la descripción, el inicio y el
        fin de cada evento desde el lunes de esta semana hasta el final de la siguiente, y los guardamos para
        enseñarle su próxima reunión, avisarle antes de que empiece y ponerlas junto a sus bloques de trabajo
        en Mi agenda. No leemos asistentes, organizador, ubicación ni adjuntos. Sólo esa
        persona ve sus eventos dentro de la app. Cada evento importado se borra 30 días después de terminar.
      </p>
      <h3>Calendario «The Agency» (permiso calendar.app.created)</h3>
      <p>
        Opcional y personal: sólo se pide a quien activa «Publicar mis bloques» en Ajustes. Con este permiso la
        app crea en su cuenta un calendario aparte llamado «The Agency» y sólo puede ver y tocar ese
        calendario, nunca los demás. En él escribe un evento por cada bloque de trabajo de esa persona, desde
        el lunes de esta semana hasta cuatro semanas después: el título de la tarea, el nombre del cliente, un
        enlace a la tarea en la app y la hora de inicio y fin. Cada minuto lee los eventos de ese calendario
        (inicio, fin y si se han borrado) para aplicar en la app lo que la persona haya movido o borrado en
        Google. De cada bloque guardamos sólo el identificador de su evento y cuándo cambió por última vez en
        Google. Borrar un evento en Google borra el bloque, nunca la tarea.
      </p>

      <h2>Para qué los usamos</h2>
      <ul>
        <li>Seguir el tráfico de las webs de nuestros clientes en su ficha.</li>
        <li>Ver en la ficha qué búsquedas, páginas y secciones ganan o pierden tráfico y cuánto viene de la marca.</li>
        <li>Ver cómo ha evolucionado la posición de cada búsqueda en los últimos meses.</li>
        <li>Ver qué páginas de entrada y qué canales traen leads a cada cliente.</li>
        <li>Añadir un bloque de cifras al resumen mensual que enviamos a cada cliente y a la página de sólo lectura que el cliente puede abrir con su enlace privado: los totales del mes y, en los mensuales, las búsquedas y páginas que más visitas trajeron, las que están cerca de la primera página y la parte que llega con la marca.</li>
        <li>Enseñar a cada persona su próxima reunión y sus reuniones de la semana junto a sus bloques de trabajo, avisarla antes y, si su equipo lo tiene activado, incluir el título y la hora en su plan de la mañana, que puede publicarse en el canal interno del equipo.</li>
        <li>Que quien lo active vea y mueva sus bloques de trabajo desde su propio Google Calendar.</li>
      </ul>
      <p>
        No usamos estos datos para publicidad, no los vendemos y no los usamos para entrenar modelos de
        inteligencia artificial. Las cifras de Google se pintan con código: no se envían a ningún servicio de IA.
      </p>
      <p>
        El uso y la transferencia a cualquier otra aplicación de la información recibida de las APIs de Google
        se ajustará a la{" "}
        <a href="https://developers.google.com/terms/api-services-user-data-policy">Política de datos de usuario de los servicios de API de Google</a>,
        incluidos los requisitos de uso limitado.
      </p>

      <h2>Quién los ve</h2>
      <p>
        Las cifras de Search Console y Analytics las ven, dentro de la app, las personas con permiso de
        lectura sobre clientes o resúmenes, y el cliente al que pertenecen. Los eventos de calendario sólo los
        ve su dueño. El calendario «The Agency» está en la cuenta de Google de esa persona: lo ve ella y
        quien ella decida en Google. No compartimos los datos con terceros salvo con los proveedores que alojan la app
        (Railway, servidor y base de datos PostgreSQL).
      </p>

      <h2>Cómo los protegemos</h2>
      <p>
        Los tokens de Google se guardan cifrados. Las conexiones van siempre por HTTPS. Conectar y desconectar
        cuentas de Search Console y Analytics sólo lo puede hacer un administrador.
      </p>

      <h2>Cuánto tiempo los guardamos y cómo borrarlos</h2>
      <p>
        Las cifras diarias de Search Console y Analytics se conservan mientras dure la relación con el cliente,
        para poder comparar con meses anteriores. El detalle por búsqueda y página se borra a los 120 días, y
        también cuando la web deja de estar asociada a un cliente activo. El total mensual por búsqueda se
        conserva como mucho 16 meses y se borra antes si la web deja de estar asociada a un cliente activo; el
        importado de nuestra herramienta anterior se conserva mientras la web esté asociada a un cliente activo.
        Las búsquedas y páginas guardadas con un resumen mensual se conservan con ese resumen y se borran
        con él o cuando la web deja de estar asociada a un cliente activo.
        Los leads por página de entrada y canal se conservan como mucho 16 meses y se borran antes si la
        propiedad de Analytics deja de estar asociada a un cliente activo. Los eventos de calendario importados
        se borran automáticamente 30 días después de terminar.
      </p>
      <ul>
        <li>
          Al desconectar cualquier cuenta de Google en la app, The Agency borra el token guardado y pide a Google
          que revoque su acceso a esa cuenta.
        </li>
        <li>
          Al desconectar una cuenta de Search Console y Analytics, el administrador puede elegir borrar también
          las cifras importadas de las webs y propiedades que se leían con ella; el borrado incluye el detalle
          por búsqueda y página, el total mensual por búsqueda (también el importado de nuestra herramienta
          anterior), las búsquedas y páginas guardadas con los resúmenes mensuales y los leads por página de
          entrada. Si no lo elige, se conservan.
        </li>
        <li>Al desconectar Google Calendar se borran todos los eventos importados de esa persona.</li>
        <li>
          Al dejar de publicar los bloques o al desconectar Google Calendar, la persona puede elegir borrar
          también el calendario «The Agency» de su Google (opción marcada por defecto). Si no lo elige, se
          queda en su cuenta como estaba y ya no se actualiza. En los dos casos la app olvida qué evento
          correspondía a cada bloque.
        </li>
      </ul>
      <p>
        Si quieres que borremos otros datos, escríbenos a <a href={`mailto:${CONTACT}`}>{CONTACT}</a> y lo
        haremos. También puedes retirar el acceso de The Agency en cualquier momento desde{" "}
        <a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.
      </p>

      <h2 lang="en">In English</h2>
      <div lang="en" className="space-y-3">
        <p>
          This policy covers The Agency (agency.magnifytools.com), operated by Magnify. Contact: {CONTACT}.
        </p>
        <p>
          <strong>Google Search Console (webmasters.readonly)</strong>: an admin connects a Google account
          with access to our clients' websites. We store that account's email and an encrypted token, and for
          each website one daily total of clicks, impressions and average position, and for 120 days the
          same daily figures per search query and per page, as aggregated and anonymised by Google, to see
          which searches, pages and sections gain or lose traffic and how much comes from the brand. Beyond
          those 120 days, we keep only a monthly total per search query (clicks, impressions and average
          position) for up to 16 months while the site is linked to an active client, to show how its
          position evolves. For some sites we also keep monthly per-query totals older than those 16 months,
          with the same Search Console data, imported once from our previous tool; they are kept while the
          site is linked to an active client. With each monthly report we also store that month's top
          searches and pages, the searches close to the first page (up to five of each) and how many clicks
          came with and without the brand, so a delivered report does not change. No countries or devices.
        </p>
        <p>
          <strong>Google Analytics (analytics.readonly)</strong>: per property and day, sessions, key events,
          and sessions and key events coming from AI assistants. The session source is only used to compute
          that share and is not stored. We also store, per day, landing page and channel (organic search,
          paid search, social…), the number of events that count as a lead for that client (as configured in
          the app, such as a form submission), already aggregated by Google, for up to 16 months; for some
          properties this includes days imported once from our previous tool. No user-level data.
        </p>
        <p>
          <strong>Google Calendar (calendar.readonly)</strong>: each user may connect their own calendar. We
          read the title, description, start and end of events from Monday of the current week to the end
          of the next one and store them to show that user their next meeting, remind them before it starts
          and place them next to their work blocks in their agenda; if their team enables it, the title
          and time appear in their morning plan, which can be posted to the team's internal channel. We do not
          read attendees, organizer, location or attachments. Only that user sees their events in the app.
          Each imported event is deleted 30 days after it ends.
        </p>
        <p>
          <strong>"The Agency" calendar (calendar.app.created)</strong>: optional and per user, requested only
          when a user turns on "Publish my blocks" in Settings. With this permission the app creates a separate
          calendar called "The Agency" in their account and can only see and change that calendar, never the
          others. It writes one event per work block of that user, from Monday of the current week to four
          weeks later: the task title, the client name, a link to the task in the app and the start and end
          time. Every minute it reads the events of that calendar (start, end and whether they were deleted) to
          apply in the app what the user moved or deleted in Google. For each block we only store its event
          ID and when it last changed in Google. Deleting an event in Google deletes the block, never the
          task. The calendar lives in the user's Google account and is visible to them and to whoever they
          share it with in Google. When they stop publishing or disconnect Google Calendar they can choose to
          also delete that calendar from Google (checked by default); otherwise it stays as it was and is no
          longer updated.
        </p>
        <p>
          Search Console and Analytics figures are shown to app users with read access to clients or reports,
          added to the monthly report sent to that client (totals and, in monthly reports, that month's top
          searches and pages, near-first-page searches and brand share), and shown on the client's private
          read-only page.
          We do not use Google data for advertising, do not sell it, and do not use it to train AI models;
          Google figures are rendered by code and are not sent to any AI service. Data is shared only with our
          hosting providers (Railway, PostgreSQL database).
        </p>
        <p>
          The Agency's use and transfer to any other app of information received from Google APIs will adhere
          to the{" "}
          <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>,
          including the Limited Use requirements.
        </p>
        <p>
          Tokens are stored encrypted and all traffic uses HTTPS. Search Console and Analytics daily figures
          are kept for the duration of the client relationship to allow comparisons with previous months.
          Query and page detail is deleted after 120 days or when the site is no longer linked to an active
          client. Monthly per-query totals are kept for up to 16 months and deleted earlier when the site is
          no longer linked to an active client; those imported from our previous tool are kept while the site
          is linked to an active client. The searches and pages stored with a monthly report are kept with
          that report and deleted with it or when the site is no longer linked to an active client. Lead events per landing page and channel are kept for up to 16 months
          and deleted earlier when the Analytics property is no longer linked to an active client. Imported
          calendar events are deleted automatically 30 days
          after they end. Disconnecting any Google
          account deletes the stored token and asks Google to revoke The Agency's access to it. When
          disconnecting a Search Console and Analytics account, the admin can choose to also delete the
          figures imported for the websites and properties read through it, including query and page detail,
          monthly per-query totals (also those imported from our previous tool), the searches and pages
          stored with monthly reports and lead events per landing page; otherwise they are kept.
          Disconnecting Google Calendar deletes all of that user's imported events. To have other data
          deleted, email {CONTACT}. You can revoke The Agency's access at any time at
          myaccount.google.com/permissions.
        </p>
      </div>
    </LegalLayout>
  )
}
