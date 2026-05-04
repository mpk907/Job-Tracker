"""Classify a job by seniority and decide whether it's 'digital'."""

import re

# ---- Seniority ------------------------------------------------------------
# Order matters: scan from highest to lowest so "VP Engineering" doesn't match
# the "engineering" half and end up as Mid.

SENIORITY_PATTERNS = [
    ("c_level",   re.compile(r"\b(chief\s+\w+\s+officer|c[-]?level|cto|cio|cdo|cmo|cfo|ceo|cpo)\b", re.I)),
    ("vp",        re.compile(r"\b(vice\s*president|vp|svp|evp|head\s+of)\b", re.I)),
    ("director",  re.compile(r"\b(director|associate\s+director|sr\.?\s+director|senior\s+director|executive\s+director)\b", re.I)),
    ("principal", re.compile(r"\b(principal|distinguished|fellow|staff)\b", re.I)),
    ("lead",      re.compile(r"\b(lead|leader|manager|sr\.?\s+manager|senior\s+manager|group\s+manager|team\s+lead)\b", re.I)),
    ("senior",    re.compile(r"\b(senior|sr\.?|sen\.?)\b", re.I)),
    ("mid",       re.compile(r"\b(ii|iii|specialist|associate|consultant|engineer|scientist|analyst|developer|designer|manager)\b", re.I)),
    ("junior",    re.compile(r"\b(junior|jr\.?|entry|graduate|trainee|apprentice|i\b|associate\s+i)\b", re.I)),
    ("intern",    re.compile(r"\b(intern|internship|working\s+student|werkstudent|student|praktikum|praktikant|co[-]?op)\b", re.I)),
]

SENIORITY_RANK = {
    "c_level":   8,
    "vp":        7,
    "director":  6,
    "principal": 5,
    "lead":      4,
    "senior":    3,
    "mid":       2,
    "junior":    1,
    "intern":    0,
    "unknown":  -1,
}

SENIORITY_LABELS = {
    "c_level":   "C-Level",
    "vp":        "VP / Head Of",
    "director":  "Director",
    "principal": "Principal / Staff",
    "lead":      "Lead / Manager",
    "senior":    "Senior",
    "mid":       "Mid",
    "junior":    "Junior",
    "intern":    "Intern / Student",
    "unknown":   "Unspecified",
}


def classify_seniority(title: str) -> str:
    if not title:
        return "unknown"
    for level, pat in SENIORITY_PATTERNS:
        if pat.search(title):
            return level
    return "unknown"


# ---- "Digital" filter ----------------------------------------------------
# A role is considered "digital" when its title or department touches one of
# these themes. We're permissive on purpose; the frontend can filter further.

DIGITAL_KEYWORDS = [
    # core digital / tech
    "digital", "data", "analytics", "ai", "artificial intelligence", "ml",
    "machine learning", "deep learning", "nlp", "llm", "genai", "generative",
    # software / engineering
    "software", "engineer", "engineering", "developer", "devops", "sre",
    "platform", "cloud", "aws", "azure", "gcp", "kubernetes", "backend",
    "frontend", "full stack", "fullstack", "mobile", "ios", "android",
    "architect", "infrastructure", "cybersecurity", "security",
    # product / design / agile
    "product manager", "product owner", "ux", "ui", "designer", "design",
    "agile", "scrum", "technical program", "technical product",
    # data science / informatics
    "data scientist", "data engineer", "bioinformatic", "computational",
    "biostatistic", "informatics", "statistician", "quant",
    # digital health themes
    "digital health", "digital therapeutic", "ehealth", "health tech",
    "telehealth", "telemedicine", "digital transformation", "rwd", "rwe",
    "real world evidence", "real-world data", "clinical informatics",
    "wearable", "iot", "remote monitoring", "decentralized trial", "dct",
    # automation / mlops
    "automation", "robotics", "mlops", "data ops", "data ops",
    # commercial-digital intersection
    "marketing technology", "martech", "crm", "salesforce", "veeva",
    "omnichannel", "customer data",
]
DIGITAL_REGEX = re.compile(r"\b(" + "|".join(re.escape(k) for k in DIGITAL_KEYWORDS) + r")\b", re.I)


def is_digital(title: str, department: str = "", extra: str = "") -> bool:
    blob = " ".join(filter(None, [title, department, extra]))
    return bool(DIGITAL_REGEX.search(blob))


# ---- Health/Pharma context (only used for generic job boards) -----------
HEALTH_KEYWORDS = [
    "pharma", "pharmaceutical", "biotech", "biopharm", "drug", "clinical",
    "medical", "medicine", "health", "healthcare", "patient", "therapeutic",
    "diagnostic", "genomic", "oncology", "oncolog", "immunolog", "neuro",
    "cardio", "vaccine", "rwd", "rwe", "real-world", "trial", "fda", "ema",
    "regulatory", "gxp", "gcp", "gmp", "life science", "biolog", "molecul",
    "wearable", "medtech", "digital therapeutic", "telemedicine", "telehealth",
    "ehr", "emr", "hipaa", "hl7", "fhir",
]
HEALTH_REGEX = re.compile(r"\b(" + "|".join(re.escape(k) for k in HEALTH_KEYWORDS) + r")\b", re.I)


def is_health_related(*texts: str) -> bool:
    """Permissive check that any of the inputs (title, company, tags, desc)
    looks pharma/health/life-sciences flavored. Used to filter generic boards."""
    blob = " ".join(filter(None, texts))
    return bool(HEALTH_REGEX.search(blob))


# ---- Company-type heuristics for board-sourced jobs ---------------------
# Board jobs have arbitrary company names; we infer their bucket via fuzzy
# substring matches against known patterns.

_TYPE_RULES = [
    ("big_pharma", [
        "pfizer", "novartis", "astrazeneca", "gsk", "glaxosmith", "sanofi",
        "takeda", "eli lilly", "lilly", "merck", "msd", "roche", "genentech",
        "bayer", "boehringer", "bristol myers", "bristol-myers", "bms",
        "johnson & johnson", "johnson and johnson", "j&j", "janssen",
        "abbvie", "abbott", "novo nordisk", "viatris", "teva",
    ]),
    ("specialist_pharma", [
        "moderna", "biontech", "vertex", "regeneron", "gilead", "alexion",
        "biogen", "celgene", "incyte", "alkermes", "ipsen", "lundbeck",
        "almirall", "csl", "ucb", "galapagos", "genmab", "argenx", "leo pharma",
        "blueprint", "kymera", "olema", "relay therapeutic", "altos labs",
    ]),
    ("ai_biotech", [
        "recursion", "isomorphic", "insitro", "atomwise", "benevolent",
        "owkin", "absci", "generate biomedicines", "valo", "exscientia",
        "schrodinger", "deep genomics", "tessera", "xtalpi", "insilico",
        "altos labs",
    ]),
    ("cro_tech_provider", [
        "iqvia", "parexel", "syneos", "icon plc", "ppd", "labcorp", "covance",
        "veeva", "medable", "saama", "saama tech", "indegene", "trialspark",
        "clinical ink", "phastar", "worldwide clinical trials", "siro clinpharm",
    ]),
    ("agency", [
        "publicis", "klick", "ogilvy", "real chemistry", "wpp", "havas health",
        "fcb health", "mccann health", "syneos health communications",
        "21grams", "intouch solutions", "evoke", "digitas health",
    ]),
    ("medtech", [
        "medtronic", "abbott", "siemens healthineers", "ge healthcare",
        "philips", "stryker", "becton dickinson", "boston scientific",
        "dexcom", "edwards lifesciences", "intuitive surgical", "danaher",
        "thermo fisher", "agilent", "illumina", "10x genomics", "natera",
        "guardant", "exact sciences",
    ]),
    ("payer", [
        "unitedhealth", "optum", "cigna", "humana", "elevance", "anthem",
        "centene", "molina", "kaiser permanente", "blue cross", "bcbs",
    ]),
    ("provider", [
        "hca healthcare", "cleveland clinic", "mayo clinic", "mass general",
        "kaiser", "ascension", "tenet", "chs", "memorial sloan",
    ]),
    ("scaleup", [
        "tempus", "verily", "flatiron", "komodo", "doctolib", "kry", "livi",
        "babylon", "zocdoc", "one medical", "hims", "hers", "ro", "sword",
        "hinge health", "whoop", "color health", "oscar health", "headway",
        "talkspace", "modern health", "lyra", "spring health", "carbon health",
        "maven clinic", "omada", "cohere health", "honor", "natera",
    ]),
    ("startup", [
        "abridge", "atropos", "tennr", "unlearn", "mama health", "overjet",
        "aidoc", "paige", "memora", "atroposhealth",
    ]),
]


def classify_company_type(name: str) -> str:
    n = (name or "").lower()
    for tp, needles in _TYPE_RULES:
        for needle in needles:
            if needle in n:
                return tp
    return "unknown"


_TYPE_LABELS_EXTRA = {
    "cro_tech_provider": "CRO / Tech Provider",
    "agency":            "Pharma Marketing Agency",
    "medtech":           "MedTech / Devices",
    "payer":             "Payer / Insurance",
    "unknown":           "Other / Via Job Board",
}
