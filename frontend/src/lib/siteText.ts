// Text for the public website (landing page). The app's own text is in i18n.ts.
import type { Lang } from "./i18n";

interface Titled {
  title: string;
  body: string;
}

export interface SiteText {
  nav: { how: string; features: string; privacy: string; faq: string; open: string };
  hero: { eyebrow: string; titleParts: [string, string, string]; lead: string; cta: string; secondary: string; points: string[] };
  mock: {
    label: string;
    status: { checking: string; checked: string };
    bill: { provider: string; statement: string; lines: { desc: string; amt: string }[]; dueLabel: string; due: string; eob: string };
    badges: [string, string];
    title: string;
    owed: [string, string];
    letter: string;
  };
  meet: { title: string; lead: string; link: string };
  bento: {
    checks: Titled;
    compare: Titled & { bill: string; eob: string };
    letters: Titled & { verified: string };
    photo: Titled & { blurry: string; retake: string; clear: string };
    rehearse: Titled & { rep: string; repLine: string; you: string; youLine: string; tips: string[] };
    refund: Titled & { found: string; amount: string };
    radar: Titled & { rows: string[]; reports: string; note: string };
  };
  how: {
    label: string;
    title: string;
    steps: Titled[];
    upload: { files: string[]; ok: string };
    confirm: { edit: string; button: string };
    act: { letter: string; greeting: string; pdf: string; copy: string };
  };
  checks: { title: string; lead: string; items: Titled[] };
  mission: { label: string; quote: string; body: string };
  stats: { value: number; suffix: string; label: string }[];
  privacy: { title: string; lead: string; items: string[]; link: string };
  faq: { title: string; items: { q: string; a: string }[] };
  cta: { title: string; body: string; button: string; floats: [string, string][]; pills: string[] };
  footer: {
    tagline: string;
    disclaimer: string;
    product: string;
    trust: string;
    openSource: string;
    privacy: string;
    terms: string;
    deletion: string;
    verify: string;
    source: string;
    license: string;
  };
  langToggle: string;
}

const en: SiteText = {
  nav: { how: "How it works", features: "Features", privacy: "Privacy", faq: "FAQ", open: "Check my bill" },
  hero: {
    eyebrow: "Medical bill checker",
    titleParts: ["Find the ", "mistakes", " in your medical bill."],
    lead:
      "Upload your bill and your insurer's Explanation of Benefits. Clyvexa compares them line by line, explains what it finds in plain language, and writes the letter to send.",
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
    owed: ["You may owe ", " less"],
    letter: "Get the letter",
  },
  meet: {
    title: "A second pair of eyes for every medical bill.",
    lead: "Clyvexa reads your bill and your insurance statement, checks one against the other, and tells you in plain words what doesn't add up, with the exact lines as proof.",
    link: "See how it works",
  },
  bento: {
    checks: { title: "8 checks on every bill", body: "Each one a fixed rule applied to the numbers, never a guess." },
    compare: { title: "Bill and EOB, side by side", body: "What the bill asks for, next to what your insurer says you owe.", bill: "Bill asks", eob: "EOB says" },
    letters: { title: "Letters you can verify", body: "Every PDF carries a QR code that proves it hasn't been changed.", verified: "Unchanged" },
    photo: { title: "Photo check on your phone", body: "Blurry, dark or cut-off photos are caught before you upload.", blurry: "Too blurry", retake: "Retake", clear: "Clear photo" },
    rehearse: {
      title: "Practice the phone call",
      body: "Rehearse with a simulated billing representative, then get a score and tips before you dial.",
      rep: "Billing",
      repLine: "Thanks for calling. How can I help?",
      you: "You",
      youLine: "I was charged twice for my visit on March 3.",
      tips: ["Clear", "Calm", "Asked for a reference number"],
    },
    refund: { title: "Refund finder", body: "Add what you've paid across bills, and Clyvexa looks for money owed back to you.", found: "you may have overpaid", amount: "$84.00" },
    radar: {
      title: "Billing error radar",
      body: "See which errors other people found with a provider.",
      rows: ["Duplicate charges", "Billed after a denial", "Network mismatch"],
      reports: "reports",
      note: "Shown only after 10+ people report it",
    },
  },
  how: {
    label: "How it works",
    title: "From photo to letter in a few minutes.",
    steps: [
      { title: "Upload", body: "Add your bill as a PDF or photos, one per page, and the EOB from your insurer if you have it. A quick check on your device tells you if a photo is too blurry, dark or cut off." },
      { title: "Confirm", body: "Clyvexa reads the totals and every line. You see what it read and can fix anything before it checks." },
      { title: "Act", body: "Get each finding with the lines it's based on, a plain-language explanation, and a ready-to-send letter as text or PDF." },
    ],
    upload: { files: ["bill-page-1.jpg", "bill-page-2.jpg", "eob-march.pdf"], ok: "Clear" },
    confirm: { edit: "Edit", button: "Looks right, check it" },
    act: { letter: "Dispute letter", greeting: "To the billing department,", pdf: "Download PDF", copy: "Copy text" },
  },
  checks: {
    title: "What it checks",
    lead: "Every finding comes from a fixed rule applied to the numbers on your documents, and shows the lines it is based on.",
    items: [
      { title: "Duplicate charges", body: "The same service billed more than once on the same day." },
      { title: "Bill doesn't match the EOB", body: "The bill asks for more than your insurer says you owe." },
      { title: "Billed after a denial", body: "You're asked to pay for a service your insurer denied, before the denial was resolved." },
      { title: "Network mismatch", body: "An in-network visit billed as out-of-network." },
      { title: "Charges not on the EOB", body: "Lines your insurer never saw, or amounts that differ from what was sent to them." },
      { title: "Payments not applied", body: "Insurance or your own payments missing from the balance, and credits owed back to you." },
      { title: "Unbundled codes", body: "Procedure pairs that are normally billed as one, using public Medicare coding edits." },
      { title: "No itemized bill", body: "A summary bill with no line-by-line detail, so you know to ask for one." },
    ],
  },
  mission: {
    label: "Why Clyvexa",
    quote: "“You shouldn't have to be a billing expert to pay a fair bill.”",
    body: "Medical bills are hard to read, and checking one against an insurance statement takes time and know-how. Clyvexa does the checking. You decide what to send.",
  },
  stats: [
    { value: 8, suffix: "", label: "checks on every bill" },
    { value: 24, suffix: "h", label: "until your uploaded files are deleted" },
    { value: 90, suffix: " days", label: "results are kept, then deleted" },
    { value: 0, suffix: "", label: "ads or tracking cookies" },
  ],
  privacy: {
    title: "Built for sensitive documents.",
    lead: "A medical bill says a lot about you. Clyvexa keeps as little as it can, for as short a time as it can.",
    items: [
      "Files and results are encrypted (AES-256) on our servers.",
      "Your original files are deleted 24 hours after upload.",
      "Results are kept 90 days, and you can delete them, or your whole account, at any time.",
      "Sharing anonymized results for research is off unless you turn it on.",
      "The photo check runs on your own device, before anything is uploaded.",
    ],
    link: "Read the privacy policy",
  },
  faq: {
    title: "Questions, answered.",
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
  cta: {
    title: "Take a second look before you pay.",
    body: "It takes a few minutes and a photo of your bill.",
    button: "Check my bill",
    floats: [
      ["Duplicate charge found", "Cargo duplicado"],
      ["Your letter is ready", "Su carta está lista"],
      ["You may owe $315.60 less", "Podría deber $315.60 menos"],
      ["Checked against your EOB", "Comparada con su EOB"],
      ["Refund found", "Reembolso encontrado"],
      ["Photo is clear", "La foto está clara"],
    ],
    pills: ["8 checks", "English and Spanish", "Files deleted after 24h", "Open source"],
  },
  footer: {
    tagline: "Clyvexa helps patients understand and question their medical bills.",
    disclaimer: "Clyvexa is not a law firm, a medical provider or an insurer, and does not give legal, medical or financial advice.",
    product: "Product",
    trust: "Trust",
    openSource: "Open source",
    privacy: "Privacy",
    terms: "Terms",
    deletion: "Delete your account",
    verify: "Verify a letter",
    source: "Source code",
    license: "MIT license",
  },
  langToggle: "Español",
};

const es: SiteText = {
  nav: { how: "Cómo funciona", features: "Funciones", privacy: "Privacidad", faq: "Preguntas", open: "Revisar mi factura" },
  hero: {
    eyebrow: "Revisión de facturas médicas",
    titleParts: ["Encuentre los ", "errores", " de su factura médica."],
    lead:
      "Suba su factura y la Explicación de Beneficios (EOB) de su seguro. Clyvexa las compara línea por línea, explica lo que encuentra en palabras sencillas y escribe la carta para enviar.",
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
    owed: ["Podría deber ", " menos"],
    letter: "Obtener la carta",
  },
  meet: {
    title: "Un segundo par de ojos para cada factura médica.",
    lead: "Clyvexa lee su factura y el estado de cuenta de su seguro, compara uno con el otro y le dice en palabras sencillas lo que no cuadra, con las líneas exactas como prueba.",
    link: "Ver cómo funciona",
  },
  bento: {
    checks: { title: "8 revisiones en cada factura", body: "Cada una es una regla fija aplicada a los números, nunca una suposición." },
    compare: { title: "Factura y EOB, lado a lado", body: "Lo que pide la factura, junto a lo que su seguro dice que usted debe.", bill: "La factura pide", eob: "La EOB dice" },
    letters: { title: "Cartas verificables", body: "Cada PDF lleva un código QR que demuestra que no ha sido cambiado.", verified: "Sin cambios" },
    photo: { title: "Revisión de fotos en su teléfono", body: "Las fotos borrosas, oscuras o cortadas se detectan antes de subirlas.", blurry: "Muy borrosa", retake: "Repetir", clear: "Foto clara" },
    rehearse: {
      title: "Practique la llamada",
      body: "Ensaye con un representante de facturación simulado y reciba una puntuación y consejos antes de marcar.",
      rep: "Facturación",
      repLine: "Gracias por llamar. ¿En qué le puedo ayudar?",
      you: "Usted",
      youLine: "Me cobraron dos veces la consulta del 3 de marzo.",
      tips: ["Claro", "Tranquilo", "Pidió un número de referencia"],
    },
    refund: { title: "Buscador de reembolsos", body: "Agregue lo que ha pagado en varias facturas y Clyvexa busca dinero que le deben devolver.", found: "podría haber pagado de más", amount: "$84.00" },
    radar: {
      title: "Radar de errores",
      body: "Vea qué errores otras personas encontraron con un proveedor.",
      rows: ["Cargos duplicados", "Cobro tras denegación", "Error de red"],
      reports: "reportes",
      note: "Solo se muestra con 10+ reportes",
    },
  },
  how: {
    label: "Cómo funciona",
    title: "De una foto a una carta en pocos minutos.",
    steps: [
      { title: "Suba", body: "Agregue su factura en PDF o fotos, una por página, y la EOB de su seguro si la tiene. Una revisión rápida en su dispositivo le avisa si una foto está borrosa, oscura o cortada." },
      { title: "Confirme", body: "Clyvexa lee los totales y cada línea. Usted ve lo que leyó y puede corregir cualquier cosa antes de la revisión." },
      { title: "Actúe", body: "Reciba cada hallazgo con las líneas en que se basa, una explicación sencilla y una carta lista para enviar, en texto o PDF." },
    ],
    upload: { files: ["factura-pagina-1.jpg", "factura-pagina-2.jpg", "eob-marzo.pdf"], ok: "Clara" },
    confirm: { edit: "Editar", button: "Está bien, revisar" },
    act: { letter: "Carta de disputa", greeting: "Al departamento de facturación:", pdf: "Descargar PDF", copy: "Copiar texto" },
  },
  checks: {
    title: "Qué revisa",
    lead: "Cada hallazgo sale de una regla fija aplicada a los números de sus documentos, y muestra las líneas en que se basa.",
    items: [
      { title: "Cargos duplicados", body: "El mismo servicio cobrado más de una vez el mismo día." },
      { title: "La factura no coincide con la EOB", body: "La factura pide más de lo que su seguro dice que usted debe." },
      { title: "Cobro después de una denegación", body: "Se le pide pagar un servicio que su seguro denegó, antes de resolver la denegación." },
      { title: "Error de red", body: "Una visita dentro de la red cobrada como fuera de la red." },
      { title: "Cargos que no están en la EOB", body: "Líneas que su seguro nunca vio, o montos distintos de los que se le enviaron." },
      { title: "Pagos no aplicados", body: "Pagos del seguro o suyos que faltan en el saldo, y créditos que le deben devolver." },
      { title: "Códigos separados", body: "Pares de procedimientos que normalmente se cobran como uno, según las reglas públicas de codificación de Medicare." },
      { title: "Sin factura detallada", body: "Una factura resumida sin detalle por línea, para que sepa pedir una." },
    ],
  },
  mission: {
    label: "Por qué Clyvexa",
    quote: "“No debería tener que ser experto en facturación para pagar una factura justa.”",
    body: "Las facturas médicas son difíciles de leer, y compararlas con el estado de cuenta del seguro toma tiempo y conocimiento. Clyvexa hace la revisión. Usted decide qué enviar.",
  },
  stats: [
    { value: 8, suffix: "", label: "revisiones en cada factura" },
    { value: 24, suffix: " h", label: "hasta que se borran sus archivos" },
    { value: 90, suffix: " días", label: "se guardan los resultados, luego se borran" },
    { value: 0, suffix: "", label: "anuncios o cookies de rastreo" },
  ],
  privacy: {
    title: "Hecho para documentos delicados.",
    lead: "Una factura médica dice mucho de usted. Clyvexa guarda lo menos posible, por el menor tiempo posible.",
    items: [
      "Los archivos y resultados se cifran (AES-256) en nuestros servidores.",
      "Sus archivos originales se borran 24 horas después de subirlos.",
      "Los resultados se guardan 90 días, y puede borrarlos, o toda su cuenta, en cualquier momento.",
      "Compartir resultados anónimos para investigación está desactivado a menos que usted lo active.",
      "La revisión de fotos se hace en su propio dispositivo, antes de subir nada.",
    ],
    link: "Leer la política de privacidad (en inglés)",
  },
  faq: {
    title: "Preguntas y respuestas.",
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
  cta: {
    title: "Dele una segunda mirada antes de pagar.",
    body: "Toma unos minutos y una foto de su factura.",
    button: "Revisar mi factura",
    floats: [
      ["Cargo duplicado", "Duplicate charge found"],
      ["Su carta está lista", "Your letter is ready"],
      ["Podría deber $315.60 menos", "You may owe $315.60 less"],
      ["Comparada con su EOB", "Checked against your EOB"],
      ["Reembolso encontrado", "Refund found"],
      ["La foto está clara", "Photo is clear"],
    ],
    pills: ["8 revisiones", "Inglés y español", "Archivos borrados tras 24 h", "Código abierto"],
  },
  footer: {
    tagline: "Clyvexa ayuda a los pacientes a entender y cuestionar sus facturas médicas.",
    disclaimer: "Clyvexa no es un bufete de abogados, un proveedor médico ni una aseguradora, y no da asesoría legal, médica ni financiera.",
    product: "Producto",
    trust: "Confianza",
    openSource: "Código abierto",
    privacy: "Privacidad",
    terms: "Términos",
    deletion: "Borrar su cuenta",
    verify: "Verificar una carta",
    source: "Código fuente",
    license: "Licencia MIT",
  },
  langToggle: "English",
};

export const SITE_TEXT: Record<Lang, SiteText> = { en, es };
