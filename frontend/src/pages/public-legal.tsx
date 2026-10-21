import type { ReactNode } from "react"
import { Link } from "react-router-dom"

/**
 * Páginas públicas sin login (/acerca y /privacidad) para la verificación de
 * Google OAuth: Google exige una página de inicio que describa la app y una
 * política que explique qué datos de Google lee y qué hace con ellos.
 * No se indexan (meta aquí + X-Robots-Tag en backend/main.py).
 *
 * Lo que cuentan debe coincidir con el código: gsc_service, gsc_detail_service,
 * ga4_service, google_calendar_service y sus rutas. Si cambia qué se guarda, se cambia aquí.
 */

const CONTACT = "david@magnify.ing"
const UPDATED = "22 de octubre de 2026"

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
          media de las webs de nuestros clientes, y el detalle por búsqueda y página de los últimos 120 días,
          para seguir su tráfico y añadir un bloque de cifras al resumen mensual que reciben.
        </li>
        <li>
          <strong>Google Analytics</strong> (sólo lectura): importa cada día las visitas, las conversiones
          (eventos clave) y la parte de las visitas que llega desde asistentes de IA, con el mismo fin.
        </li>
        <li>
          <strong>Google Calendar</strong> (sólo lectura, opcional y personal): cada persona puede conectar
          su calendario para ver su próxima reunión en su lista de tareas.
        </li>
      </ul>
      <p>
        The Agency nunca escribe, modifica ni borra nada en las cuentas de Google. Lo único que pide a Google
        es retirar su propio acceso cuando se desconecta una cuenta.
      </p>
      <p>
        Detalle completo en la <Link to="/privacidad">política de privacidad</Link>.
      </p>

      <h2 lang="en">In English</h2>
      <div lang="en" className="space-y-3">
        <p>
          The Agency is the operations tool of Magnify, an SEO consultancy. It is used by our team and by
          collaborators and clients we invite; there is no public sign-up. It reads Google Search Console
          (including per-query and per-page detail for the last 120 days) and Google Analytics data
          (read-only) for our clients' websites to track their traffic and to add
          a block of figures to the monthly report each client receives. Each user may optionally connect
          their own Google Calendar (read-only) to see their next meeting. The app never writes to, changes
          or deletes anything in Google accounts; the only request it makes is to revoke its own access when
          an account is disconnected. See the <Link to="/privacidad">privacy policy</Link>.
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
        y separar el tráfico de marca. Las consultas son las que Google ya muestra agregadas y anonimizadas en
        Search Console: no identifican a ninguna persona. No guardamos países ni dispositivos.
      </p>
      <h3>Google Analytics (permiso analytics.readonly)</h3>
      <p>
        Con las mismas cuentas, guardamos por propiedad y día: visitas (sesiones), conversiones (eventos
        clave) y las visitas y conversiones que llegan desde asistentes de IA. La fuente de cada visita sólo
        se usa para calcular esa parte; no se guarda. No guardamos datos de usuarios individuales.
      </p>
      <h3>Google Calendar (permiso calendar.readonly)</h3>
      <p>
        Cada persona puede conectar su propio calendario. Leemos de los próximos 7 días el título, la
        descripción, el inicio y el fin de cada evento, y los guardamos para enseñarle su próxima reunión y
        avisarle antes de que empiece. No leemos asistentes, organizador, ubicación ni adjuntos. Sólo esa
        persona ve sus eventos dentro de la app. Cada evento importado se borra 30 días después de terminar.
      </p>

      <h2>Para qué los usamos</h2>
      <ul>
        <li>Seguir el tráfico de las webs de nuestros clientes en su ficha.</li>
        <li>Ver en la ficha qué búsquedas, páginas y secciones ganan o pierden tráfico y cuánto viene de la marca.</li>
        <li>Añadir un bloque de cifras al resumen mensual que enviamos a cada cliente y a la página de sólo lectura que el cliente puede abrir con su enlace privado.</li>
        <li>Enseñar a cada persona su próxima reunión, avisarla antes y, si su equipo lo tiene activado, incluir el título y la hora en su plan de la mañana, que puede publicarse en el canal interno del equipo.</li>
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
        ve su dueño. No compartimos los datos con terceros salvo con los proveedores que alojan la app
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
        también cuando la web deja de estar asociada a un cliente activo. Los eventos de calendario importados
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
          por búsqueda y página. Si no lo elige, se conservan.
        </li>
        <li>Al desconectar Google Calendar se borran todos los eventos importados de esa persona.</li>
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
          which searches, pages and sections gain or lose traffic and how much comes from the brand. No
          countries or devices.
        </p>
        <p>
          <strong>Google Analytics (analytics.readonly)</strong>: per property and day, sessions, key events,
          and sessions and key events coming from AI assistants. The session source is only used to compute
          that share and is not stored. No user-level data.
        </p>
        <p>
          <strong>Google Calendar (calendar.readonly)</strong>: each user may connect their own calendar. We
          read the title, description, start and end of events in the next 7 days and store them to show
          that user their next meeting and remind them before it starts; if their team enables it, the title
          and time appear in their morning plan, which can be posted to the team's internal channel. We do not
          read attendees, organizer, location or attachments. Only that user sees their events in the app.
          Each imported event is deleted 30 days after it ends.
        </p>
        <p>
          Search Console and Analytics figures are shown to app users with read access to clients or reports,
          added to the monthly report sent to that client, and shown on the client's private read-only page.
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
          client. Imported calendar events are deleted automatically 30 days after they end. Disconnecting any Google
          account deletes the stored token and asks Google to revoke The Agency's access to it. When
          disconnecting a Search Console and Analytics account, the admin can choose to also delete the
          figures imported for the websites and properties read through it, including query and page detail;
          otherwise they are kept.
          Disconnecting Google Calendar deletes all of that user's imported events. To have other data
          deleted, email {CONTACT}. You can revoke The Agency's access at any time at
          myaccount.google.com/permissions.
        </p>
      </div>
    </LegalLayout>
  )
}
