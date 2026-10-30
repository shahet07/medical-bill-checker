"""Retrieval eval set: realistic questions and the guide that should answer them."""

QUERIES = [
    ("What is an EOB and is it a bill?", "reading-an-eob"),
    ("What does allowed amount mean on my insurance statement?", "reading-an-eob"),
    ("How do I get an itemized bill from the hospital?", "itemized-bills"),
    ("How long does the hospital have to send me my billing records?", "itemized-bills"),
    ("I think I was charged twice for the same test", "common-billing-errors"),
    ("My insurance denied my claim, how do I appeal?", "denied-claims-and-appeals"),
    ("How long do I have to file an appeal?", "denied-claims-and-appeals"),
    ("I got a huge bill from an out-of-network anesthesiologist at my in-network hospital", "no-surprises-act"),
    ("Does the surprise billing law cover ambulance rides?", "no-surprises-act"),
    ("I don't have insurance and my bill is way more than the estimate", "good-faith-estimates"),
    ("Can I get free or reduced-cost care because of my income?", "financial-assistance"),
    ("Can I pay my hospital bill in monthly installments?", "payment-plans"),
    ("What is balance billing?", "network-status"),
    ("What do the codes and modifiers on my bill mean?", "medical-codes"),
    ("Will this medical bill hurt my credit score?", "medical-debt"),
    ("What does 'payment may not be applied' mean in this tool?", "about-the-flags"),
]

SPANISH_QUERIES = [
    ("¿Cómo apelo una reclamación negada por mi seguro?", "denied-claims-and-appeals"),
    ("¿Puedo pedir ayuda financiera al hospital por mis ingresos?", "financial-assistance"),
    ("¿Qué es una factura detallada y cómo la pido?", "itemized-bills"),
    ("¿Esta deuda médica afecta mi crédito?", "medical-debt"),
]
