"""Spanish -> English translation of card values for the cover prompt.

SD 1.5's CLIP text encoder is English-only: a raw Spanish card value
("una paloma") degrades into junk BPE fragments and the model draws whatever
it wants. Cards are typed in Spanish in the admin panel, so their values are
translated before they reach the prompt.

This is a small rule-based translator, not a general one: it runs offline, in
microseconds, with no model to load next to llama-server and Stable Diffusion.
It knows the vocabulary of children's stories and four pieces of grammar:

- gender, number and diminutives fall back to the base word
  ("gata" -> cat, "perros" -> dogs, "conejito" -> little rabbit);
- articles are dropped, connectors are translated ("y" -> and, "con" -> with);
- adjectives move in front of their noun ("gato negro" -> black cat);
- a word that is both a colour and a thing takes the thing when it stands
  alone ("rosa" -> rose, "pantera rosa" -> pink panther).

Unknown words pass through unchanged (best effort), and
``translate_with_coverage`` reports them so the caller can ask llama-server
for those values instead (``cover_llm_translator``) when it is available.
"""

import unicodedata

# Keys are accent-folded, lowercase, masculine singular where a word inflects.
_NOUNS = {
    # --- animals ---
    "paloma": "dove",
    "pichon": "pigeon",
    "buho": "owl",
    "lechuza": "owl",
    "canguro": "kangaroo",
    "leon": "lion",
    "tigre": "tiger",
    "elefante": "elephant",
    "mono": "monkey",
    "gorila": "gorilla",
    "raton": "mouse",
    "rata": "rat",
    "pez": "fish",
    "ballena": "whale",
    "delfin": "dolphin",
    "tiburon": "shark",
    "pulpo": "octopus",
    "cangrejo": "crab",
    "tortuga": "turtle",
    "caracol": "snail",
    "conejo": "rabbit",
    "liebre": "hare",
    "perro": "dog",
    "cachorro": "puppy",
    "gato": "cat",
    "vaca": "cow",
    "toro": "bull",
    "cerdo": "pig",
    "caballo": "horse",
    "poni": "pony",
    "burro": "donkey",
    "zorro": "fox",
    "lobo": "wolf",
    "oso": "bear",
    "panda": "panda",
    "koala": "koala",
    "rana": "frog",
    "sapo": "toad",
    "pajaro": "bird",
    "pollito": "chick",
    "pollo": "chicken",
    "gallina": "hen",
    "gallo": "rooster",
    "pato": "duck",
    "ganso": "goose",
    "cisne": "swan",
    "loro": "parrot",
    "aguila": "eagle",
    "pinguino": "penguin",
    "oveja": "sheep",
    "cordero": "lamb",
    "cabra": "goat",
    "ciervo": "deer",
    "ardilla": "squirrel",
    "erizo": "hedgehog",
    "topo": "mole",
    "murcielago": "bat",
    "mariposa": "butterfly",
    "abeja": "bee",
    "mariquita": "ladybug",
    "hormiga": "ant",
    "arana": "spider",
    "gusano": "worm",
    "oruga": "caterpillar",
    "lagarto": "lizard",
    "serpiente": "snake",
    "cocodrilo": "crocodile",
    "hipopotamo": "hippo",
    "rinoceronte": "rhino",
    "jirafa": "giraffe",
    "cebra": "zebra",
    "camello": "camel",
    "foca": "seal",
    "dinosaurio": "dinosaur",
    "animal": "animal",
    "mascota": "pet",
    # --- fantasy and story characters ---
    "dragon": "dragon",
    "unicornio": "unicorn",
    "hada": "fairy",
    "duende": "elf",
    "elfo": "elf",
    "gnomo": "gnome",
    "enano": "dwarf",
    "gigante": "giant",
    "ogro": "ogre",
    "trol": "troll",
    "monstruo": "monster",
    "fantasma": "ghost",
    "bruja": "witch",
    "brujo": "wizard",
    "mago": "wizard",
    "hechicero": "wizard",
    "genio": "genie",
    "sirena": "mermaid",
    "angel": "angel",
    "vampiro": "vampire",
    "momia": "mummy",
    "esqueleto": "skeleton",
    "robot": "robot",
    "extraterrestre": "alien",
    "alien": "alien",
    "marciano": "alien",
    "superheroe": "superhero",
    "heroe": "hero",
    "ninja": "ninja",
    "pirata": "pirate",
    "vaquero": "cowboy",
    "caballero": "knight",
    "princesa": "princess",
    "principe": "prince",
    "rey": "king",
    "reina": "queen",
    "payaso": "clown",
    "muneco": "doll",
    "muneca": "doll",
    # --- people ---
    "nino": "boy",
    "nina": "girl",
    "bebe": "baby",
    "chico": "boy",
    "chica": "girl",
    "hombre": "man",
    "mujer": "woman",
    "senor": "man",
    "senora": "woman",
    "abuelo": "grandfather",
    "abuela": "grandmother",
    "papa": "dad",
    "padre": "father",
    "mama": "mom",
    "madre": "mother",
    "hermano": "brother",
    "hermana": "sister",
    "amigo": "friend",
    "familia": "family",
    "maestro": "teacher",
    "profesor": "teacher",
    "medico": "doctor",
    "doctor": "doctor",
    "enfermero": "nurse",
    "bombero": "firefighter",
    "policia": "police officer",
    "astronauta": "astronaut",
    "piloto": "pilot",
    "marinero": "sailor",
    "pescador": "fisherman",
    "granjero": "farmer",
    "cocinero": "cook",
    "panadero": "baker",
    "pintor": "painter",
    "musico": "musician",
    "bailarin": "dancer",
    "bailarina": "ballerina",
    "detective": "detective",
    "explorador": "explorer",
    "cientifico": "scientist",
    "jardinero": "gardener",
    "cartero": "mail carrier",
    # --- places ---
    "castillo": "castle",
    "palacio": "palace",
    "torre": "tower",
    "bosque": "forest",
    "selva": "jungle",
    "jardin": "garden",
    "parque": "park",
    "playa": "beach",
    "montana": "mountain",
    "volcan": "volcano",
    "rio": "river",
    "lago": "lake",
    "mar": "sea",
    "oceano": "ocean",
    "granja": "farm",
    "campo": "countryside",
    "pradera": "meadow",
    "ciudad": "city",
    "pueblo": "town",
    "calle": "street",
    "casa": "house",
    "cabana": "cabin",
    "escuela": "school",
    "colegio": "school",
    "cueva": "cave",
    "isla": "island",
    "desierto": "desert",
    "nieve": "snow",
    "espacio": "outer space",
    "planeta": "planet",
    "cielo": "sky",
    "circo": "circus",
    "zoo": "zoo",
    "zoologico": "zoo",
    "mercado": "market",
    "tienda": "shop",
    "cocina": "kitchen",
    "habitacion": "bedroom",
    "puente": "bridge",
    "camino": "path",
    "faro": "lighthouse",
    "molino": "windmill",
    "iglesia": "church",
    "hospital": "hospital",
    "biblioteca": "library",
    "museo": "museum",
    "estacion": "station",
    "puerto": "harbor",
    "piscina": "swimming pool",
    "arbol": "tree",
    # --- objects ---
    "flor": "flower",
    "estrella": "star",
    "luna": "moon",
    "sol": "sun",
    "corazon": "heart",
    "regalo": "gift",
    "bola": "ball",
    "pelota": "ball",
    "balon": "ball",
    "globo": "balloon",
    "cometa": "kite",
    "libro": "book",
    "cuento": "storybook",
    "lapiz": "pencil",
    "campana": "bell",
    "llave": "key",
    "puerta": "door",
    "ventana": "window",
    "corona": "crown",
    "espada": "sword",
    "escudo": "shield",
    "varita": "wand",
    "escoba": "broom",
    "pocion": "potion",
    "tesoro": "treasure",
    "cofre": "treasure chest",
    "mapa": "map",
    "nube": "cloud",
    "lluvia": "rain",
    "arcoiris": "rainbow",
    "paraguas": "umbrella",
    "sombrero": "hat",
    "gorro": "cap",
    "bota": "boot",
    "zapato": "shoe",
    "capa": "cape",
    "vestido": "dress",
    "bufanda": "scarf",
    "gafas": "glasses",
    "mochila": "backpack",
    "reloj": "clock",
    "linterna": "lantern",
    "lampara": "lamp",
    "vela": "candle",
    "espejo": "mirror",
    "caja": "box",
    "cesta": "basket",
    "juguete": "toy",
    "peluche": "teddy bear",
    "tambor": "drum",
    "guitarra": "guitar",
    "flauta": "flute",
    "trompeta": "trumpet",
    "piano": "piano",
    "camara": "camera",
    "telescopio": "telescope",
    "coche": "car",
    "carro": "cart",
    "camion": "truck",
    "autobus": "bus",
    "tren": "train",
    "bicicleta": "bicycle",
    "bici": "bicycle",
    "barco": "boat",
    "avion": "airplane",
    "cohete": "rocket",
    "nave": "spaceship",
    "manzana": "apple",
    "platano": "banana",
    "fresa": "strawberry",
    "zanahoria": "carrot",
    "queso": "cheese",
    "pan": "bread",
    "tarta": "cake",
    "pastel": "cake",
    "galleta": "cookie",
    "helado": "ice cream",
    "caramelo": "candy",
    "chocolate": "chocolate",
    "miel": "honey",
    "leche": "milk",
    "huevo": "egg",
    "seta": "mushroom",
    "hoja": "leaf",
    "piedra": "stone",
    "concha": "seashell",
    "pluma": "feather",
    "hueso": "bone",
    "nido": "nest",
    "hielo": "ice",
    "fuego": "fire",
    "agua": "water",
    "musica": "music",
    "amor": "love",
}

_ADJECTIVES = {
    # --- emotions ---
    "feliz": "happy",
    "contento": "happy",
    "alegre": "cheerful",
    "triste": "sad",
    "asustado": "scared",
    "enojado": "angry",
    "enfadado": "angry",
    "furioso": "furious",
    "orgulloso": "proud",
    "sorprendido": "surprised",
    "cansado": "tired",
    "dormido": "sleepy",
    "hambriento": "hungry",
    "solo": "lonely",
    "valiente": "brave",
    "timido": "shy",
    "nervioso": "nervous",
    "tranquilo": "calm",
    "curioso": "curious",
    "divertido": "funny",
    "gracioso": "funny",
    "travieso": "playful",
    "jugueton": "playful",
    "amable": "kind",
    "carinoso": "loving",
    "enamorado": "in love",
    "preocupado": "worried",
    "aburrido": "bored",
    "emocionado": "excited",
    "confundido": "confused",
    "celoso": "jealous",
    "grunon": "grumpy",
    "pensativo": "thoughtful",
    # Emotion cards are often typed as nouns ("con miedo", "alegría").
    "miedo": "scared",
    "alegria": "joyful",
    "tristeza": "sad",
    "rabia": "angry",
    "sueno": "sleepy",
    "hambre": "hungry",
    "sorpresa": "surprised",
    "verguenza": "shy",
    # --- size, shape, quality ---
    "grande": "big",
    "gran": "big",
    "enorme": "huge",
    "pequeno": "small",
    "chiquito": "tiny",
    "alto": "tall",
    "bajo": "short",
    "largo": "long",
    "gordo": "chubby",
    "delgado": "thin",
    "rapido": "fast",
    "lento": "slow",
    "bonito": "pretty",
    "lindo": "cute",
    "hermoso": "beautiful",
    "feo": "ugly",
    "viejo": "old",
    "joven": "young",
    "nuevo": "new",
    "fuerte": "strong",
    "sabio": "wise",
    "listo": "clever",
    "magico": "magic",
    "encantado": "enchanted",
    "polar": "polar",
    "marino": "sea",
    "volador": "flying",
    "brillante": "shiny",
    "dorado": "golden",
    "plateado": "silver",
    "peludo": "fluffy",
    "suave": "soft",
    "dulce": "sweet",
    "frio": "cold",
    "caliente": "hot",
    "bueno": "good",
    "buen": "good",
    "malo": "naughty",
    # --- colours ---
    "azul": "blue",
    "verde": "green",
    "rojo": "red",
    "amarillo": "yellow",
    "naranja": "orange",
    "morado": "purple",
    "violeta": "purple",
    "rosa": "pink",
    "rosado": "pink",
    "negro": "black",
    "blanco": "white",
    "gris": "gray",
    "marron": "brown",
    # --- quantity (already in front of the noun in Spanish) ---
    "dos": "two",
    "tres": "three",
    "cuatro": "four",
    "cinco": "five",
    "mucho": "many",
    "muy": "very",
}

# Words that are both a colour and a thing: the thing when they stand alone
# or lead the value, the colour after a noun.
_NOUN_SENSES = {
    "rosa": "rose",
    "violeta": "violet",
}

# Articles and possessives carry nothing the model can use.
_DROPPED = {
    "un",
    "una",
    "unos",
    "unas",
    "el",
    "la",
    "los",
    "las",
    "al",
    "mi",
    "mis",
    "su",
    "sus",
    "tu",
    "tus",
}

# Fixed expressions that do not translate word by word. Keys are the folded
# words with articles already dropped.
_PHRASES = {
    ("caballito", "de", "mar"): "seahorse",
    ("estrella", "de", "mar"): "starfish",
    ("pez", "payaso"): "clownfish",
    ("oso", "de", "peluche"): "teddy bear",
    ("osito", "de", "peluche"): "teddy bear",
    ("muneco", "de", "nieve"): "snowman",
    ("hombre", "de", "nieve"): "snowman",
    ("arco", "iris"): "rainbow",
    ("nave", "espacial"): "spaceship",
    ("casa", "del", "arbol"): "treehouse",
    ("casa", "de", "arbol"): "treehouse",
    ("parque", "de", "atracciones"): "amusement park",
    ("papa", "noel"): "santa claus",
    ("reyes", "magos"): "three wise kings",
    ("caperucita", "roja"): "little red riding hood",
    ("gato", "con", "botas"): "puss in boots",
    ("ratoncito", "perez"): "tooth fairy mouse",
    ("varita", "magica"): "magic wand",
    ("alfombra", "magica"): "magic carpet",
    ("bola", "de", "cristal"): "crystal ball",
}
_MAX_PHRASE_WORDS = max(len(k) for k in _PHRASES)

# Connectors are kept: "dog and cat", "cat with boots", "castle of ice".
_CONNECTORS = {
    "y": "and",
    "e": "and",
    "con": "with",
    "sin": "without",
    "de": "of",
    "del": "of",
    "en": "in",
}

_IRREGULAR_PLURALS = {
    "mouse": "mice",
    "fish": "fish",
    "sheep": "sheep",
    "deer": "deer",
    "wolf": "wolves",
    "elf": "elves",
    "dwarf": "dwarves",
    "leaf": "leaves",
    "goose": "geese",
    "man": "men",
    "woman": "women",
    "baby": "babies",
    "glasses": "glasses",
    "firefighter": "firefighters",
}

# (suffix, replacement): "gatito" -> "gato", "casita" -> "casa",
# "leoncito" -> "leon", "florecita" -> "flor".
_DIMINUTIVES = (
    ("ecito", ""),
    ("ecita", ""),
    ("cito", ""),
    ("cita", ""),
    ("ito", "o"),
    ("ita", "a"),
    ("illo", "o"),
    ("illa", "a"),
)


def fold(value: str) -> str:
    """Lowercase, trim and strip accents ("Dragón" -> "dragon")."""
    folded = unicodedata.normalize("NFD", value.strip().casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _pluralize(noun: str) -> str:
    head, _, last = noun.rpartition(" ")
    if last in _IRREGULAR_PLURALS:
        plural = _IRREGULAR_PLURALS[last]
    elif last.endswith(("s", "x", "ch", "sh")):
        plural = last + "es"
    elif last.endswith("y") and last[-2:-1] not in "aeiou":
        plural = last[:-1] + "ies"
    else:
        plural = last + "s"
    return f"{head} {plural}" if head else plural


def _number_forms(token: str):
    """Yield (candidate, is_plural): the word itself, then its singulars."""
    yield token, False
    if token.endswith("ces") and len(token) > 4:
        yield token[:-3] + "z", True  # peces -> pez
    if token.endswith("es") and len(token) > 3:
        yield token[:-2], True  # flores -> flor
    if token.endswith("s") and len(token) > 2:
        yield token[:-1], True  # gatos -> gato


def _gender_forms(stem: str):
    """Yield the word itself, then its masculine forms."""
    yield stem
    if stem.endswith("a") and len(stem) > 2:
        yield stem[:-1] + "o"  # gata -> gato
        yield stem[:-1]  # leona -> leon


def _base_forms(stem: str):
    """Yield (candidate, is_diminutive) for a singular word."""
    for form in _gender_forms(stem):
        yield form, False
    for suffix, replacement in _DIMINUTIVES:
        if stem.endswith(suffix) and len(stem) > len(suffix) + 2:
            base = stem[: -len(suffix)] + replacement
            for form in _gender_forms(base):
                yield form, True


def _lookup(token: str) -> tuple[str, bool] | None:
    """Translate one folded Spanish word.

    Returns (english, is_adjective), or None when the word is unknown.
    """
    for stem, plural in _number_forms(token):
        for base, little in _base_forms(stem):
            if base in _ADJECTIVES:
                return _ADJECTIVES[base], True
            if base in _NOUNS:
                english = _NOUNS[base]
                if plural:
                    english = _pluralize(english)
                if little:
                    english = f"little {english}"
                return english, False
    return None


def _translate_word(token: str, words: list[tuple[str, str]]) -> tuple[str, str]:
    """Translate one word given the (text, kind) words already emitted."""
    if token in _CONNECTORS:
        return _CONNECTORS[token], "conn"
    after_noun = bool(words) and words[-1][1] in _NOUN_KINDS
    if token in _NOUN_SENSES and not after_noun:
        return _NOUN_SENSES[token], "noun"
    found = _lookup(token)
    if found is None:
        return token, "unknown"
    return found[0], "adj" if found[1] else "noun"


# Unknown words are treated as nouns, so "zorp azul" still becomes "blue zorp".
_NOUN_KINDS = ("noun", "unknown")


def translate(value: str) -> str:
    """Best-effort ES->EN translation of a card value for the CLIP encoder.

    Returns an empty string when nothing drawable is left (a value made only
    of articles and connectors), so the caller can drop the parameter.
    """
    return translate_with_coverage(value)[0]


def translate_with_coverage(value: str) -> tuple[str, bool]:
    """Translate a card value and report whether every word was known.

    Returns (english, complete). ``complete`` is False when at least one word
    passed through untranslated — the signal to ask llama-server instead
    (``cover_llm_translator``).
    """
    # (text, kind) with kind in {"noun", "adj", "conn", "unknown"}.
    words: list[tuple[str, str]] = []
    tokens = [t for t in fold(value).replace(",", " ").split() if t not in _DROPPED]
    pos = 0
    while pos < len(tokens):
        for size in range(min(_MAX_PHRASE_WORDS, len(tokens) - pos), 1, -1):
            phrase = _PHRASES.get(tuple(tokens[pos : pos + size]))
            if phrase:
                words.append((phrase, "noun"))
                pos += size
                break
        else:
            words.append(_translate_word(tokens[pos], words))
            pos += 1

    # Connectors only make sense between two words.
    while words and words[0][1] == "conn":
        words.pop(0)
    while words and words[-1][1] == "conn":
        words.pop()
    if not words:
        return "", True
    complete = all(kind != "unknown" for _, kind in words)

    # Spanish puts adjectives after the noun, English before it:
    # "gato negro y blanco" -> "black and white cat".
    out: list[str] = []
    i = 0
    while i < len(words):
        text, kind = words[i]
        if kind not in _NOUN_KINDS:
            out.append(text)
            i += 1
            continue
        j = i + 1
        trailing: list[str] = []
        while j < len(words):
            if words[j][1] == "adj":
                trailing.append(words[j][0])
                j += 1
            elif (
                words[j][0] == "and"
                and trailing
                and j + 1 < len(words)
                and words[j + 1][1] == "adj"
            ):
                trailing.append("and")
                j += 1
            else:
                break
        out.extend(trailing)
        out.append(text)
        i = j
    return " ".join(out), complete
