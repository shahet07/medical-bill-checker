// Text for the public website (landing page). The app's own text is in i18n.ts.
import type { Lang } from "./i18n";

export interface SiteText {
  nav: { how: string; features: string; privacy: string; faq: string; open: string };
  hero: { eyebrow: string; titleParts: [string, string, string]; lead: string; cta: string; secondary: string; points: string[] };
  mock: {
    label: string;
    status: { checking: string; checked: string };
    bill: { provider: string; statement: string; lines: { desc: string; amt: string }[]; dueLabel: string; due: string; eob: string };
    badges: [string, string];
    title: string;
    flags: { title: string; detail: string }[];
    owed: [string, string];
    letter: string;
  };
  stats: { value: number; suffix: string; label: string }[];
  how: { title: string; steps: { title: string; body: string }[] };
  checks: { title: string; lead: string; items: { title: string; body: string }[] };
  features: { title: string; items: { title: string; body: string }[] };
  privacy: { title: string; lead: string; items: string[]; link: string };
  faq: { title: string; items: { q: string; a: string }[] };
  cta: { title: string; body: string; button: string };
  footer: { tagline: string; disclaimer: string; privacy: string; terms: string; deletion: string; verify: string; source: string };
  langToggle: string;
}

const en: SiteText = {
  nav: { how: "How it works", features: "Features", privacy: "Privacy", faq: "FAQ", open: "Check my bill" },
  hero: {
    eyebrow: "Medical bill checker",
    titleParts: ["Find the ", "mistakes", " in your medical bill before you pay it."],
    lead:
      "Upload your bill and your insurer's Explanation of Benefits. Clyvexa reads both, compares them line by line, explains what it finds in plain language, and writes the letter to send.",
    cta: "Check my bill",
    secondary: "See how it works",
    points: ["PDF or phone photos", "English and Spanish", "Open source"],
  },
  mock: {
    label: "Example: a sample bill being checked",
    status: { checking: "Checking…", checked: "Checked" },
    bill: {
      provider: "Example Medical Center",
      statement: "Patient statement",
      lines: [
        { desc: "Office visit (99214)", amt: "$210.00" },
        { desc: "Office visit (99214)", amt: "$210.00" },
        { desc: "Metabolic panel (80053)", amt: "$86.00" },
        { desc: "Insurance paid", amt: "−$94.00" },
      ],
      dueLabel: "Amount due",
      due: "$412.00",
      eob: "Your insurer's EOB says you owe $96.40",
    },
    badges: ["Charged twice", "Doesn't match EOB"],
    title: "2 things to check",
    flags: [
      { title: "Charged twice", detail: "Office visit 99214 appears on the same day twice." },
      { title: "More than your insurer says you owe", detail: "Bill asks $412.00. EOB says $96.40." },
    ],
    owed: ["You may owe ", " less"],
    letter: "Get the letter",
  },
  stats: [
    { value: 8, suffix: "", label: "checks on every bill" },
    { value: 2, suffix: "", label: "languages, English and Spanish" },
    { value: 24, suffix: "h", label: "until your uploaded files are deleted" },
    { value: 0, suffix: "", label: "ads or tracking cookies" },
  ],
  how: {
    title: "How it works",
    steps: [
      {
        title: "Upload",
        body: "Add your bill as a PDF or photos, one per page. Add the EOB from your insurer if you have it. A quick check on your device tells you if a photo is too blurry, dark or cut off.",
      },
      {
        title: "Confirm",
        body: "Clyvexa reads the totals and every line. You see what it read and can fix anything before it checks.",
      },
      {
        title: "Act",
        body: "Get each finding with the exact lines it is based on, a plain-language explanation, and a ready-to-send letter as text or PDF.",
      },
    ],
  },
  checks: {
    title: "What it checks",
    lead: "Every finding comes from a fixed rule applied to the numbers on your documents, not from a guess, and shows the lines it is based on.",
    items: [
      { title: "Duplicate charges", body: "The same service billed more than once on the same day." },
      { title: "Bill doesn't match the EOB", body: "The bill asks for more than your insurer says you owe." },
      { title: "Billed after a denial", body: "You are asked to pay for a service your insurer denied, before the denial was resolved." },
      { title: "Network mismatch", body: "An in-network visit billed as out-of-network." },
      { title: "Charges not on the EOB", body: "Lines your insurer never saw, or amounts that differ from what was sent to them." },
      { title: "Payments not applied", body: "Insurance or your own payments missing from the balance, and credits owed back to you." },
      { title: "Unbundled codes", body: "Procedure pairs that are normally billed as one (using public Medicare coding edits)." },
      { title: "No itemized bill", body: "A summary bill with no line-by-line detail, so you know to ask for one." },
    ],
  },
  features: {
    title: "More than a checker",
    items: [
      { title: "Letters that hold up", body: "Dispute and itemization request letters, as text or PDF. Each PDF carries a QR code anyone can scan to confirm the letter hasn't been changed." },
      { title: "Practice the phone call", body: "Rehearse the call with a simulated billing representative, then get a score and tips before you dial." },
      { title: "Refund finder", body: "Add what you've paid across bills and Clyvexa looks for overpayments you can ask to get back." },
      { title: "Billing error radar", body: "See which errors other people have found with a provider. Shown only once at least 10 people report a pattern, never who." },
      { title: "Ask questions", body: "Ask about your bill in your own words. Answers cite the guides they come from." },
      { title: "Plain words", body: "Every term explained, every amount shown in context, in English or Spanish." },
    ],
  },
  privacy: {
    title: "Built for sensitive documents",
    lead: "A medical bill says a lot about you. Clyvexa is designed to keep as little as it can, for as short a time as it can.",
    items: [
      "Files and results are encrypted (AES-256) on our servers.",
      "Your original files are deleted 24 hours after upload.",
      "Results are kept 90 days so you can come back, and you can delete them, or your whole account, at any time.",
      "Sharing anonymized results for research is off unless you turn it on, and never includes your name, provider, account numbers, dates or files.",
      "The photo check runs on your own device, before anything is uploaded.",
    ],
    link: "Read the privacy policy",
  },
  faq: {
    title: "Questions",
    items: [
      {
        q: "Is this legal, medical or financial advice?",
        a: "No. Clyvexa points out things worth checking and helps you ask about them. The provider or insurer decides whether a charge is correct. For a large or urgent bill, consider a patient advocate.",
      },
      {
        q: "Does Clyvexa contact my provider or insurer?",
        a: "No. You stay in control: Clyvexa writes the letter and helps you prepare for the call, and you decide whether to send it.",
      },
      {
        q: "Do I need the Explanation of Benefits (EOB)?",
        a: "No, but it helps a lot. With the EOB, Clyvexa can compare what your insurer says you owe with what the bill asks for. Your insurer's website or app usually has it.",
      },
      {
        q: "Which bills does it work with?",
        a: "Bills from US hospitals, clinics, labs and doctors, with or without insurance. PDF files and photos (JPG, PNG, iPhone HEIC) up to 20 pages.",
      },
      {
        q: "Who sees my bill?",
        a: "To read your documents, their content is sent to an AI service (Google Gemini or Anthropic Claude, depending on how the service is set up). The privacy policy explains what is shared and kept.",
      },
      {
        q: "What if nothing is found?",
        a: "That's good news, but not a guarantee the bill is right. You still get a plain-language summary and can ask for an itemized bill.",
      },
    ],
  },
  cta: { title: "Take a second look before you pay.", body: "It takes a few minutes and a photo of your bill.", button: "Check my bill" },
  footer: {
    tagline: "Clyvexa helps patients understand and question their medical bills.",
    disclaimer: "Clyvexa is not a law firm, a medical provider or an insurer, and does not give legal, medical or financial advice.",
    privacy: "Privacy",
    terms: "Terms",
    deletion: "Delete your account",
    verify: "Verify a letter",
    source: "Source code",
  },
  langToggle: "Español",
};

const es: SiteText = {
  nav: { how: "Cómo funciona", features: "Funciones", privacy: "Privacidad", faq: "Preguntas", open: "Revisar mi factura" },
  hero: {
    eyebrow: "Revisión de facturas médicas",
    titleParts: ["Encuentre los ", "errores", " de su factura médica antes de pagarla."],
    lead:
      "Suba su factura y la Explicación de Beneficios (EOB) de su seguro. Clyvexa lee ambas, las compara línea por línea, explica lo que encuentra en palabras sencillas y escribe la carta para enviar.",
    cta: "Revisar mi factura",
    secondary: "Ver cómo funciona",
    points: ["PDF o fotos del teléfono", "Inglés y español", "Código abierto"],
  },
  mock: {
    label: "Ejemplo: revisión de una factura de muestra",
    status: { checking: "Revisando…", checked: "Revisada" },
    bill: {
      provider: "Centro Médico de Ejemplo",
      statement: "Estado de cuenta",
      lines: [
        { desc: "Consulta (99214)", amt: "$210.00" },
        { desc: "Consulta (99214)", amt: "$210.00" },
        { desc: "Panel metabólico (80053)", amt: "$86.00" },
        { desc: "Pago del seguro", amt: "−$94.00" },
      ],
      dueLabel: "Monto a pagar",
      due: "$412.00",
      eob: "La EOB de su seguro dice que debe $96.40",
    },
    badges: ["Cobrado dos veces", "No coincide con la EOB"],
    title: "2 cosas para revisar",
    flags: [
      { title: "Cobrado dos veces", detail: "La consulta 99214 aparece dos veces el mismo día." },
      { title: "Más de lo que su seguro dice que debe", detail: "La factura pide $412.00. La EOB dice $96.40." },
    ],
    owed: ["Podría deber ", " menos"],
    letter: "Obtener la carta",
  },
  stats: [
    { value: 8, suffix: "", label: "revisiones en cada factura" },
    { value: 2, suffix: "", label: "idiomas, inglés y español" },
    { value: 24, suffix: " h", label: "hasta que se borran sus archivos" },
    { value: 0, suffix: "", label: "anuncios o cookies de rastreo" },
  ],
  how: {
    title: "Cómo funciona",
    steps: [
      {
        title: "Suba",
        body: "Agregue su factura en PDF o fotos, una por página. Agregue la EOB de su seguro si la tiene. Una revisión rápida en su dispositivo le avisa si una foto está borrosa, oscura o cortada.",
      },
      {
        title: "Confirme",
        body: "Clyvexa lee los totales y cada línea. Usted ve lo que leyó y puede corregir cualquier cosa antes de la revisión.",
      },
      {
        title: "Actúe",
        body: "Reciba cada hallazgo con las líneas exactas en que se basa, una explicación sencilla y una carta lista para enviar, en texto o PDF.",
      },
    ],
  },
  checks: {
    title: "Qué revisa",
    lead: "Cada hallazgo sale de una regla fija aplicada a los números de sus documentos, no de una suposición, y muestra las líneas en que se basa.",
    items: [
      { title: "Cargos duplicados", body: "El mismo servicio cobrado más de una vez el mismo día." },
      { title: "La factura no coincide con la EOB", body: "La factura pide más de lo que su seguro dice que usted debe." },
      { title: "Cobro después de una denegación", body: "Se le pide pagar un servicio que su seguro denegó, antes de resolver la denegación." },
      { title: "Error de red", body: "Una visita dentro de la red cobrada como fuera de la red." },
      { title: "Cargos que no están en la EOB", body: "Líneas que su seguro nunca vio, o montos distintos de los que se le enviaron." },
      { title: "Pagos no aplicados", body: "Pagos del seguro o suyos que faltan en el saldo, y créditos que le deben devolver." },
      { title: "Códigos separados", body: "Pares de procedimientos que normalmente se cobran como uno (según las reglas públicas de codificación de Medicare)." },
      { title: "Sin factura detallada", body: "Una factura resumida sin detalle por línea, para que sepa pedir una." },
    ],
  },
  features: {
    title: "Más que una revisión",
    items: [
      { title: "Cartas que se sostienen", body: "Cartas de disputa y de solicitud de factura detallada, en texto o PDF. Cada PDF lleva un código QR que cualquiera puede escanear para confirmar que la carta no ha sido cambiada." },
      { title: "Practique la llamada", body: "Ensaye la llamada con un representante de facturación simulado y reciba una puntuación y consejos antes de marcar." },
      { title: "Buscador de reembolsos", body: "Agregue lo que ha pagado en varias facturas y Clyvexa busca pagos de más que puede pedir que le devuelvan." },
      { title: "Radar de errores", body: "Vea qué errores otras personas han encontrado con un proveedor. Solo se muestra cuando al menos 10 personas reportan un patrón, nunca quiénes." },
      { title: "Haga preguntas", body: "Pregunte sobre su factura con sus propias palabras. Las respuestas citan las guías de donde vienen." },
      { title: "Palabras sencillas", body: "Cada término explicado y cada monto en contexto, en inglés o español." },
    ],
  },
  privacy: {
    title: "Hecho para documentos delicados",
    lead: "Una factura médica dice mucho de usted. Clyvexa está diseñado para guardar lo menos posible, por el menor tiempo posible.",
    items: [
      "Los archivos y resultados se cifran (AES-256) en nuestros servidores.",
      "Sus archivos originales se borran 24 horas después de subirlos.",
      "Los resultados se guardan 90 días para que pueda volver, y puede borrarlos, o toda su cuenta, en cualquier momento.",
      "Compartir resultados anónimos para investigación está desactivado a menos que usted lo active, y nunca incluye su nombre, proveedor, números de cuenta, fechas ni archivos.",
      "La revisión de fotos se hace en su propio dispositivo, antes de subir nada.",
    ],
    link: "Leer la política de privacidad (en inglés)",
  },
  faq: {
    title: "Preguntas",
    items: [
      {
        q: "¿Es asesoría legal, médica o financiera?",
        a: "No. Clyvexa señala cosas que vale la pena revisar y le ayuda a preguntar por ellas. El proveedor o el seguro decide si un cargo es correcto. Para una factura grande o urgente, considere un defensor del paciente.",
      },
      {
        q: "¿Clyvexa contacta a mi proveedor o a mi seguro?",
        a: "No. Usted tiene el control: Clyvexa escribe la carta y le ayuda a preparar la llamada, y usted decide si la envía.",
      },
      {
        q: "¿Necesito la Explicación de Beneficios (EOB)?",
        a: "No, pero ayuda mucho. Con la EOB, Clyvexa puede comparar lo que su seguro dice que usted debe con lo que pide la factura. Suele estar en el sitio web o la aplicación de su seguro.",
      },
      {
        q: "¿Con qué facturas funciona?",
        a: "Facturas de hospitales, clínicas, laboratorios y médicos de EE. UU., con o sin seguro. Archivos PDF y fotos (JPG, PNG, HEIC de iPhone) de hasta 20 páginas.",
      },
      {
        q: "¿Quién ve mi factura?",
        a: "Para leer sus documentos, su contenido se envía a un servicio de IA (Google Gemini o Anthropic Claude, según cómo esté configurado el servicio). La política de privacidad explica qué se comparte y qué se guarda.",
      },
      {
        q: "¿Y si no encuentra nada?",
        a: "Es una buena noticia, pero no garantiza que la factura esté bien. Igual recibe un resumen sencillo y puede pedir una factura detallada.",
      },
    ],
  },
  cta: { title: "Dele una segunda mirada antes de pagar.", body: "Toma unos minutos y una foto de su factura.", button: "Revisar mi factura" },
  footer: {
    tagline: "Clyvexa ayuda a los pacientes a entender y cuestionar sus facturas médicas.",
    disclaimer: "Clyvexa no es un bufete de abogados, un proveedor médico ni una aseguradora, y no da asesoría legal, médica ni financiera.",
    privacy: "Privacidad",
    terms: "Términos",
    deletion: "Borrar su cuenta",
    verify: "Verificar una carta",
    source: "Código fuente",
  },
  langToggle: "English",
};

export const SITE_TEXT: Record<Lang, SiteText> = { en, es };
