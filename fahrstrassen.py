#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import sys
import os
import io
import argparse
from collections import defaultdict
from functools import lru_cache

try:
    from termcolor import colored
except ImportError:
    def colored(s, *args, **kwargs):
        return s

import logging
# logging.basicConfig(level = logging.DEBUG)

path_insensitive_cache = {}

# http://stackoverflow.com/a/8462613/1083696
def path_insensitive(path):
    """
    Get a case-insensitive epath for use on a case sensitive system.
    """
    try:
        return path_insensitive_cache[path]
    except KeyError:
        ret = _path_insensitive(path) or path
        path_insensitive_cache[path] = ret
        return ret

def _path_insensitive(path):
    """
    Recursive part of path_insensitive to do the work.
    """

    if path == '' or os.path.exists(path):
        return path

    base = os.path.basename(path)  # may be a directory or a file
    dirname = os.path.dirname(path)

    suffix = ''
    if not base:  # dir ends with a slash?
        if len(dirname) < len(path):
            suffix = path[:len(path) - len(dirname)]

        base = os.path.basename(dirname)
        dirname = os.path.dirname(dirname)

    if not os.path.exists(dirname):
        dirname = _path_insensitive(dirname)
        if not dirname:
            return

    # at this point, the directory exists but not the file

    try:  # we are expecting dirname to be a directory, but it could be a file
        files = os.listdir(dirname)
    except OSError:
        return

    baselow = base.lower()
    try:
        basefinal = next(fl for fl in files if fl.lower() == baselow)
    except StopIteration:
        return

    if basefinal:
        return os.path.join(dirname, basefinal) + suffix
    else:
        return

all_ones = 2**64 - 1

NORM = True
GEGEN = False

def str_el_ri(modul, element, richtung):
    global dieses_modul
    return "Element {}{}{}".format(
        element.attrib.get("Nr", "0"),
        'n' if richtung == NORM else 'g',
        "" if modul == dieses_modul else "[{}]".format(os.path.basename(modul.replace('\\', os.sep))),
    )

class RefPunkt(object):
    def __init__(self, modul, refnr, info, reftyp, element, richtung):
        self.modul = modul
        self.refnr = refnr
        self.info = info
        self.reftyp = reftyp
        self.element = element
        self.richtung = richtung

    def __repr__(self):
        global dieses_modul
        return "Element {}{}{}".format(
            self.element.attrib.get("Nr", "0"),
            'n' if self.richtung == NORM else 'g',
            "" if self.modul == dieses_modul else "[{}]".format(self.modul_kurz())
        )

    def __eq__(self, other):
        return isinstance(other, RefPunkt) and self.modul == other.modul and self.refnr == other.refnr

    def __hash__(self):
        return hash((self.modul, self.refnr))

    def valid(self):
        return self.element is not None

    def modul_kurz(self):
        return os.path.basename(self.modul.replace('\\', os.sep))

    def el_r(self):
        return (self.modul, self.element, self.richtung)

    def signal(self):
        return self.element.find("./Info" + ("Norm" if self.richtung == NORM else "Gegen") + "Richtung/Signal")

str_geschw = lambda v : "oo<{:.0f}>".format(v) if v < 0 else "{:.0f}".format(v * 3.6)

def geschw_min(v1, v2):
    if v1 < 0:
        return v2
    if v2 < 0:
        return v1
    return min(v1, v2)

def geschw_kleiner(v1, v2):
    if v2 < 0:
        return v1 >= 0
    if v1 < 0:
        return False
    return v1 < v2

def normalize_zusi_relpath(relpath):
    return relpath.upper().replace('/', '\\')

@lru_cache(maxsize=None)
def get_zusi_datapath():
    return os.environ.get("ZUSI3_DATAPATH", "")

@lru_cache(maxsize=None)
def get_zusi_datapath_official():
    try:
        return os.environ['ZUSI3_DATAPATH_OFFICIAL']
    except KeyError:
        return get_zusi_datapath()

def get_zusi_relpath(realpath):
    try:
        candidate1 = os.path.relpath(realpath, get_zusi_datapath())
    except ValueError:
        candidate1 = None

    try:
        candidate2 = os.path.relpath(realpath, get_zusi_datapath_official())
    except ValueError:
        candidate2 = None

    if candidate1 is None:
        if candidate2 is None:
            raise Exception("Kann {} nicht in Zusi-relativen Pfad umwandeln (Datenverzeichnis: {}, Datenverzeichnis offiziell: {})".format(realpath, get_zusi_datapath(), get_zusi_datapath_official()))
        else:
            return candidate2.replace('/', '\\')
    else:
        return candidate1.replace('/', '\\')

def get_abspath(zusi_relpath):
    zusi_relpath = zusi_relpath.lstrip('\\').strip().replace('\\', os.sep)
    result = path_insensitive(os.path.join(get_zusi_datapath(), zusi_relpath))
    if os.path.exists(result):
        return result
    return path_insensitive(os.path.join(get_zusi_datapath_official(), zusi_relpath))

# {fehlendes Modul}
missing = set()

# Modul -> (Elementnummer -> <StrElement>-Knoten)
streckenelemente = dict()

# Modul -> (Referenznummer -> (<StrElement>-Knoten, {NORM, GEGEN}))
referenzpunkte = dict()

# Modul -> [<Fahrstrasse>-Knoten]
fahrstrassen = dict()

# Modul -> [Modulname]
nachbarmodule = dict()

def lade_modul(zusi_relpath):
    tree = ET.parse(get_abspath(zusi_relpath))
    # Elementnummer -> <StrElement>-Knoten
    streckenelemente[zusi_relpath] = dict(
        (int(s.attrib.get("Nr", 0)), s)
        for s in tree.findall("./Strecke/StrElement")
    )
    referenzpunkte[zusi_relpath] = dict(
        (int(r.attrib.get("ReferenzNr", 0)), (streckenelemente[zusi_relpath][int(r.attrib.get("StrElement", 0))], NORM if int(r.attrib.get("StrNorm", 0)) == 1 else GEGEN, int(r.attrib.get("RefTyp", 0)), r.attrib.get("Info", "")))
        for r in tree.findall("./Strecke/ReferenzElemente")
        if int(r.attrib.get("StrElement", 0)) in streckenelemente[zusi_relpath]
    )
    fahrstrassen[zusi_relpath] = tree.findall("./Strecke/Fahrstrasse")
    nachbarmodule[zusi_relpath] = [get_modul_aus_dateiknoten(n) for n in tree.findall("./Strecke/ModulDateien")]

def get_refpunkt(modul, nummer):
    if modul not in referenzpunkte:
        modul = normalize_zusi_relpath(modul)
        if modul in missing:
            return RefPunkt(modul, nummer, "", 0, None, "")
        try:
            lade_modul(modul)
        except FileNotFoundError:
            missing.add(modul)
            return RefPunkt(modul, nummer, "", 0, None, "")

    try:
        (element, richtung, info, reftyp) = referenzpunkte[modul][nummer]
    except KeyError:
        return RefPunkt(modul, nummer, "", 0, None, "")
    return RefPunkt(modul, nummer, info, reftyp, element, richtung)

def get_element(modul, nummer):
    if modul not in streckenelemente:
        modul = normalize_zusi_relpath(modul)
        if modul in missing:
            return None
        try:
            lade_modul(modul)
        except FileNotFoundError:
            missing.add(modul)
            return None

    try:
        return streckenelemente[modul][nummer]
    except KeyError:
        return None

# Sucht Knoten ./Datei und liefert Modul zurueck (leerer String oder nicht vorhandener Knoten = Fallback; leerer Fallback = dieses Modul)
def get_modul_aus_dateiknoten(knoten, fallback=''):
    if len(fallback) == 0:
        fallback = dieses_modul
    datei = knoten.find("./Datei")
    if datei is not None:
        return normalize_zusi_relpath(datei.attrib.get("Dateiname", fallback))
    return fallback

# -----

def gegen(el_r):
    return (el_r[0], el_r[1], not el_r[2]) if el_r is not None else None

def nachfolger(el_r, index):
    (modul, el, richtung) = el_r
    if el is None:
        return None

    anschluss = int(el.attrib.get("Anschluss", 0))
    anschluss_shift = index + (8 if richtung == GEGEN else 0)

    nachfolger = [n for n in el if
        (richtung == NORM and (n.tag == "NachNorm" or n.tag == "NachNormModul")) or
        (richtung == GEGEN and (n.tag == "NachGegen" or n.tag == "NachGegenModul"))]

    if index >= len(nachfolger):
        return None

    nachfolger_knoten = nachfolger[index]
    if "Modul" not in nachfolger_knoten.tag:
        nach_modul = modul
        nach_el = get_element(nach_modul, int(nachfolger_knoten.attrib.get("Nr", 0)))
        nach_richtung = NORM if (anschluss >> anschluss_shift) & 1 == 0 else GEGEN
    else:
        nach_modul = get_modul_aus_dateiknoten(nachfolger_knoten)
        nach_ref = get_refpunkt(nach_modul, int(nachfolger_knoten.attrib.get("Nr", 0)))
        nach_el = nach_ref.element if nach_ref.valid else None
        nach_richtung = GEGEN if nach_ref.richtung == NORM else NORM

    if nach_el is None:
        return None
    return (nach_modul, nach_el, nach_richtung)

def vorgaenger(el_r):
    return gegen(nachfolger(gegen(el_r)))

# -----

# Signal-LS3 -> [Animationsname]
animationen = dict()

def get_animationen(signal_ls3_relpath):
    signal_ls3_relpath = normalize_zusi_relpath(signal_ls3_relpath)
    if signal_ls3_relpath not in animationen:
        try:
            tree = ET.parse(get_abspath(signal_ls3_relpath))
            animationen[signal_ls3_relpath] = [n.attrib.get("AniBeschreibung", "?") for n in tree.findall("./Landschaft/Animation")]
        except FileNotFoundError:
            animationen[signal_ls3_relpath] = []
    return animationen[signal_ls3_relpath]

def get_signalbild_fuer_id(signal, signalbild_id):
    idx = 0
    result = []
    for sigframe in signal.findall("./SignalFrame/Datei"):
        if "Dateiname" in sigframe.attrib:
            animationen = get_animationen(sigframe.attrib["Dateiname"])
        else:
            animationen = []
        if len(animationen) == 0:
            idx += 1
        else:
            for ani_name in animationen:
                if signalbild_id & (1 << idx) != 0:
                    result.append(ani_name)
                idx += 1

    return "?" if len(result) == 0 else " + ".join(result)

def get_signalbild_fuer_spalte(signal, spalte):
    signalbild_id = all_ones
    zeile_gefunden = False
    zeilen = signal.findall("./HsigBegriff")
    anz_spalten = len(signal.findall("./VsigBegriff"))
    matrix = signal.findall("./MatrixEintrag")

    ereignisse = None

    for idx, zeile in enumerate(zeilen):
        # Betrachte nur Zeilen fuer Zugfahrten mit Geschwindigkeit > 0,
        # sonst kann im H/V-System das Signalbild nicht bestimmt werden
        # (bei Hp0 ist Vorsignal dunkel)
        if float(zeile.attrib.get("HsigGeschw", 0.0)) != 0.0 and int(zeile.attrib.get("FahrstrTyp", 0)) & 4 != 0:
            zeile_gefunden = True
            eintrag = matrix[idx * anz_spalten + spalte]
            signalbild_id &= int(eintrag.attrib.get("Signalbild", 0))
            eintrag_ereignisse = set(int(e.attrib.get("Er", 0)) for e in eintrag.findall("./Ereignis"))
            if ereignisse is None:
                ereignisse = eintrag_ereignisse.copy()
            else:
                ereignisse = ereignisse.intersection(eintrag_ereignisse)

    if not zeile_gefunden:
        signalbild_id = 0

    return get_signalbild_fuer_id(signal, signalbild_id) + ("" if ereignisse is None or len(ereignisse) == 0 else (" + " + " + ".join(str(e) for e in ereignisse)))

def get_signalbild_fuer_zeile(signal, zeile, ersatzsignal):
    if ersatzsignal:
        try:
            ersatzsignal_knoten = signal.findall("./Ersatzsignal")[zeile]
        except IndexError:
            return '?'
        name = ersatzsignal_knoten.attrib.get("ErsatzsigBezeichnung", "?") + ": "
        eintrag_vsig_geschw_0 = ersatzsignal_knoten.find("./MatrixEintrag")
        signalbild_id = int(eintrag_vsig_geschw_0.attrib.get("Signalbild", 0))

    else:
        signalbild_id = all_ones
        anz_spalten = len(signal.findall("./VsigBegriff"))
        matrix = signal.findall("./MatrixEintrag")

        for i in range(0, anz_spalten):
            signalbild_id &= int(matrix[zeile * anz_spalten + i].attrib.get("Signalbild", 0))

        # Finde Eintrag mit Vorsignalgeschwindigkeit 0
        # (dieser wird beim Stellen der Fahrstrasse auf jeden Fall angesteuert)
        spalte_geschw_0 = 0
        for idx, vsig_begriff in enumerate(signal.findall("VsigBegriff")):
            if vsig_begriff.attrib.get("VsigGeschw", 0) == 0:
                spalte_geschw_0 = idx
                break

        eintrag_vsig_geschw_0 = matrix[zeile * anz_spalten + spalte_geschw_0]
        name = ""

    befehl_einblenden = ""
    for e in eintrag_vsig_geschw_0.findall("./Ereignis"):
        if int(e.attrib.get("Er", 0)) == 32:
            befehl_einblenden += ' + Befehl einblenden ({} m)'.format(e.attrib.get("Wert", 0))

    return name + get_signalbild_fuer_id(signal, signalbild_id) + befehl_einblenden

def get_signalbild_id_fuer_zeile_und_spalte(signal, zeile, spalte, ersatzsignal):
    if ersatzsignal:
        matrix = signal.findall("./Ersatzsignal/MatrixEintrag")
        return int(matrix[zeile].attrib.get("Signalbild", 0))
    else:
        anz_spalten = len(signal.findall("./VsigBegriff"))
        matrix = signal.findall("./MatrixEintrag")
        return int(matrix[zeile * anz_spalten + spalte].attrib.get("Signalbild", 0))

def get_signalgeschw_fuer_zeile_und_spalte(signal, zeile, spalte, ersatzsignal):
    if ersatzsignal:
        matrix = signal.findall("./Ersatzsignal/MatrixEintrag")
        return float(matrix[zeile].attrib.get("MatrixGeschw", 0))
    else:
        anz_spalten = len(signal.findall("./VsigBegriff"))
        matrix = signal.findall("./MatrixEintrag")
        return float(matrix[zeile * anz_spalten + spalte].attrib.get("MatrixGeschw", 0))

# -----
# main
# -----

parser = argparse.ArgumentParser(description='Liste von Fahrstrassen in einem Zusi-3-Modul, sowie andere Helferfunktionen.')
parser.add_argument('dateiname')
parser.add_argument('--modus', default='fahrstrassen', help='Modus. Moegliche Werte sind: "fahrstrassen" -- gib eine Liste von Fahrstrassen aus. "an_signal" -- gib eine Liste von Fahrstrassenkombinationen am angegebenen Signal (--signal) aus. "refpunkte" -- vergleiche generierte und tatsaechliche Namen von Signal-Referenzpunkten.')
parser.add_argument('--sortiert', action='store_true', help="Sortiere Fahrstrassen nach Namen")
parser.add_argument('--register', action='store_true', help="Gib auch Register in Fahrstrassen aus")
parser.add_argument('--weichen', action='store_true', help="Gib auch Weichen in Fahrstrassen aus")
parser.add_argument('--bue', action='store_true', help="Gib auch Bahnuebergangsereignisse in Fahrstrassen aus")
parser.add_argument('--hsig-ausserhalb-fahrstrasse',  default='ignorieren', choices=['ignorieren', 'ausgeben', 'ausgeben_exkl'], help="Fahrstrassen markieren oder ausgeben, bei denen ein Hauptsignal ausserhalb der Fahrstrasse liegt")
parser.add_argument('--vsig-geschw', default='ignorieren', choices=['ignorieren', 'ausgeben', 'ausgeben_exkl'], help="Fahrstrassen markieren oder ausgeben, bei denen ein Vorsignal eine hoehere Geschwindigkeit anzeigt als das Hauptsignal mit der niedrigsten Geschwindigkeit in der Fahrstrasse")
parser.add_argument('--signal', action='store', help="Signalbezeichnung (z.B. \"S3\") fuer modus=an_signal")

args = parser.parse_args()

dieses_modul = get_zusi_relpath(os.path.realpath(args.dateiname))
logging.debug("Dieses Modul: {} -> {}".format(args.dateiname, dieses_modul))

lade_modul(dieses_modul)
logging.debug("{} Referenzpunkt(e), {} Fahrstrasse(n)".format(len(referenzpunkte[dieses_modul]), len(fahrstrassen[dieses_modul])))

if args.modus == 'refpunkte':
  for refnr, (element, richtung, reftyp, info) in referenzpunkte[dieses_modul].items():
    if reftyp == 4:
        sig = element.find("./Info" + ("Norm" if richtung == NORM else "Gegen") + "Richtung/Signal")
        if sig is not None:
            info_soll = 'Signal: {} {}'.format(sig.attrib.get("NameBetriebsstelle", ""), sig.attrib.get("Signalname", ""))
            if info != info_soll:
                print("Referenzpunkt {}: ist '{}', soll '{}'".format(refnr, info, info_soll))

if args.modus == 'an_signal':
    for m in nachbarmodule[dieses_modul]:
        try:
            lade_modul(m)
        except FileNotFoundError:
            pass

    refpunkte = []

    for refnr, (element, richtung, reftyp, info) in referenzpunkte[dieses_modul].items():
        if reftyp == 4:
            sig = element.find("./Info" + ("Norm" if richtung == NORM else "Gegen") + "Richtung/Signal")
            if sig is not None and (args.signal is None or sig.attrib.get("Signalname", "") == args.signal):
                refpunkte.append(get_refpunkt(dieses_modul, refnr))

    if len(refpunkte) == 0:
        print("Keine Referenzpunkte fuer Signal '{}' gefunden".format(args.signal))
    else:
        for rp in refpunkte:
            # Fahrstrassen, in denen das angegebene Signal als Hsig bzw. Vsig enthalten ist.
            hsig_fahrstrassen = set()
            vsig_fahrstrassen = set()

            for fahrstrassen_liste in fahrstrassen.values():
                for fahrstrasse in fahrstrassen_liste:
                    if any(int(n.attrib.get("Ref", 0)) == rp.refnr
                            and get_modul_aus_dateiknoten(n) == rp.modul
                            for n in fahrstrasse.findall("./FahrstrSignal")):
                        hsig_fahrstrassen.add(fahrstrasse)

                    if any(int(n.attrib.get("Ref", 0)) == rp.refnr
                            and get_modul_aus_dateiknoten(n) == rp.modul
                            for n in fahrstrasse.findall("./FahrstrVSignal")):
                        vsig_fahrstrassen.add(fahrstrasse)

            # string -> [Fahrstrassenname]
            kombinationen = defaultdict(list)

            for fahrstr_hsig in hsig_fahrstrassen:
                for fahrstr_vsig in vsig_fahrstrassen:
                    ziel1 = fahrstr_hsig.find("./FahrstrZiel")
                    start2 = fahrstr_vsig.find("./FahrstrStart")

                    if ziel1 is None or start2 is None \
                            or ziel1.attrib.get("Ref", 0) != start2.attrib.get("Ref", 0) \
                            or get_modul_aus_dateiknoten(ziel1) != get_modul_aus_dateiknoten(start2):
                        continue

                    # <Signal>-Knoten -> (zeile, spalte, ist_ersatzsignal)
                    hsig_stellungen = {}

                    for an_hsig in fahrstr_hsig.findall("./FahrstrSignal"):
                        signal = get_refpunkt(get_modul_aus_dateiknoten(an_hsig), int(an_hsig.attrib["Ref"])).signal()

                        # Finde Spalte mit Spaltengeschwindigkeit 0
                        spalte_geschw_0 = 0
                        for idx, vsig_begriff in enumerate(signal.findall("VsigBegriff")):
                            if vsig_begriff.attrib.get("VsigGeschw", 0) == 0:
                                spalte_geschw_0 = idx
                                break

                        zeile = int(an_hsig.attrib.get("FahrstrSignalZeile", 0))
                        ersatzsignal = int(an_hsig.attrib.get("FahrstrSignalErsatzsignal", 0)) == 1

                        hsig_stellungen[signal] = (zeile, spalte_geschw_0, ersatzsignal)

                    for ab_vsig in fahrstr_vsig.findall("./FahrstrVSignal"):
                        signal = get_refpunkt(get_modul_aus_dateiknoten(ab_vsig), int(ab_vsig.attrib["Ref"])).signal()

                        if signal not in hsig_stellungen:
                            continue

                        hsig_stellung = hsig_stellungen[signal]
                        spalte_neu = int(ab_vsig.attrib.get("FahrstrSignalSpalte", 0))

                        geschw_alt = get_signalgeschw_fuer_zeile_und_spalte(signal, *hsig_stellung)
                        geschw_neu = get_signalgeschw_fuer_zeile_und_spalte(signal, hsig_stellung[0], spalte_neu, hsig_stellung[2])

                        signalbild_alt = get_signalbild_id_fuer_zeile_und_spalte(signal, *hsig_stellung)
                        if geschw_alt == geschw_neu:
                            hsig_stellung_neu = (hsig_stellung[0], spalte_neu, hsig_stellung[2])
                            signalbild_neu = get_signalbild_id_fuer_zeile_und_spalte(signal, *hsig_stellung_neu)

                            weg = signalbild_alt & ~signalbild_neu
                            dazu = signalbild_neu & ~signalbild_alt

                            key = "{} -> {} ({} -> {})".format(
                                colored(get_signalbild_fuer_id(signal, weg), 'red', attrs=['bold']),
                                colored(get_signalbild_fuer_id(signal, dazu), 'blue', attrs=['bold']),
                                colored(get_signalbild_fuer_id(signal, signalbild_alt), 'red'),
                                colored(get_signalbild_fuer_id(signal, signalbild_neu), 'blue'),
                            )
                        else:
                            key = "{} -> {}".format(
                                colored(get_signalbild_fuer_id(signal, signalbild_alt), 'red', attrs=['bold']),
                                colored("<bleibt auf Vsig=0 wegen unterschiedlicher Signalgeschwindigkeiten: {} -> {}>".format(str_geschw(geschw_alt), str_geschw(geschw_neu)), 'blue', attrs=['bold']),
                            )

                        kombinationen[key].append("{} + {}".format(
                            colored(fahrstr_hsig.attrib.get("FahrstrName", ""), 'red'),
                            colored(fahrstr_vsig.attrib.get("FahrstrName", ""), 'blue'),
                        ))

            print("\n\n{} {}".format(
                colored(rp.signal().attrib.get("NameBetriebsstelle", "?"), 'grey'),
                colored(rp.signal().attrib.get("Signalname", "?"), 'grey', attrs=['bold']),
            ))

            for key, values in sorted(kombinationen.items()):
                print("\n" + key)
                for value in values:
                    print(" - " + value)

if args.modus == 'fahrstrassen':
  if args.sortiert:
    fahrstrassen[dieses_modul].sort(key = lambda f: f.attrib.get("FahrstrName", ""))
  for f in fahrstrassen[dieses_modul]:
    print_out = args.hsig_ausserhalb_fahrstrasse != 'ausgeben_exkl' and args.vsig_geschw != 'ausgeben_exkl'
    with io.StringIO() as out:
        nichtalsziel = float(f.attrib.get("ZufallsWert", 0))
        rglggl = int(f.attrib.get("RglGgl", 0))
        print("\nFahrstrasse {} {}   {}, {:.0f}m{}".format(
            f.attrib.get("FahrstrTyp", "?"),
            colored(f.attrib.get("FahrstrName", "?"), 'grey', attrs=['bold']),
            "Bahnhof" if rglggl == 0 else ("eingleisig" if rglggl == 1 else ("Regelgleis" if rglggl == 2 else ("Gegengleis" if rglggl == 3 else "?"))),
            float(f.attrib.get("Laenge", 0)),
            '' if nichtalsziel == 0 else ' (nicht als Ziel: {:.0f}%)'.format(nichtalsziel * 100)), file=out)

        min_geschw = -1

        elemente = []

        startknoten = f.find("./FahrstrStart")
        start_rp = get_refpunkt(get_modul_aus_dateiknoten(startknoten), int(startknoten.attrib.get("Ref", 0)))
        start = start_rp.el_r()

        zielknoten = f.find("./FahrstrZiel")
        ziel_rp = get_refpunkt(get_modul_aus_dateiknoten(zielknoten), int(zielknoten.attrib.get("Ref", 0)))
        ziel = ziel_rp.el_r()

        if start_rp.valid():
            print(" - {}".format(start_rp), end='', file=out)
        else:
            print(" - " + colored("Nicht aufloesbare Referenz {} in Modul {}".format(start_rp.refnr, start_rp.modul_kurz()), 'white', 'on_red'), end='', file=out)

        if ziel_rp.valid():
            print(" -> {}".format(ziel_rp), file=out)
        else:
            print(" -> " + colored("Zielpunkt mit nicht aufloesbarer Referenz {} in Modul {}".format(ziel_rp.refnr, ziel_rp.modul_kurz()), 'white', 'on_red'), file=out)

        weichen_rp = [(get_refpunkt(get_modul_aus_dateiknoten(weiche), int(weiche.attrib.get("Ref", 0))), int(weiche.attrib.get("FahrstrWeichenlage", 0)) - 1)
            for weiche in f.findall("./FahrstrWeiche")]
        weichen = dict((rp.el_r(), weichenlage) for (rp, weichenlage) in weichen_rp)

        if start_rp.valid and ziel_rp.valid:
            akt = start
            elemente.append(akt)
            cnt = 0
            while akt is not None and akt != ziel:
                akt = nachfolger(akt, weichen.get(akt, 0))
                if akt is not None:
                    elemente.append(akt)

        # Referenzpunkt -> [modul, el, ri, schliessen]
        bue = defaultdict(list)

        if args.bue:
            for modul, el, ri in elemente:
                for ereignis in el.findall("./Info" + ("Norm" if ri == NORM else "Gegen") + "Richtung/Ereignis"):
                    er_nr = int(ereignis.get("Er", 0))
                    if er_nr in {27, 1000027}:
                        # TODO: nur 1x pro Streckenmodul ausgeben
                        try:
                            rp = get_refpunkt(normalize_zusi_relpath(ereignis.get("Beschr", "")), int(ereignis.get("Wert", 0)))
                        except:
                            print(" - " + colored("Bahnuebergang oeffnen/schliessen mit ungueltiger Referenzangabe: Modul '{}', Referenznr. '{}'".format(ereignis.get("Beschr", ""), ereignis.get("Wert", "")), 'white', 'on_red') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
                        if not rp.valid():
                            print(" - " + colored("Bahnuebergang oeffnen/schliessen mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul), 'white', 'on_red') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
                            continue
                        signal = rp.signal()
                        if signal is None:
                            print(" - " + colored("Bahnuebergang oeffnen/schliessen mit fehlendem Signal an {} (Referenznummer {})".format(rp, rp.refnr), 'white', 'on_red') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
                            continue

                        bue[rp].append((modul, el, ri, er_nr == 27))

        for sig in f.findall("./FahrstrSignal"):
            rp = get_refpunkt(get_modul_aus_dateiknoten(sig), int(sig.attrib.get("Ref", 0)))
            if not rp.valid():
                print(" - " + colored("Hauptsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul_kurz()), 'white', 'on_red'), file=out)
                continue
            signal = rp.signal()
            if signal is None:
                print(" - " + colored("Hauptsignal-Referenz mit fehlendem Signal an {} (Referenznummer {})".format(rp, rp.refnr), 'white', 'on_red'), file=out)
                continue

            hat_zaehler = int(signal.attrib.get("SignalFlags", 0)) & 8 != 0
            hat_bue = False

            ersatzsignal = int(sig.attrib.get("FahrstrSignalErsatzsignal", 0)) == 1
            zeile = int(sig.attrib.get("FahrstrSignalZeile", 0))
            hsig_geschw = float(signal.findall("./HsigBegriff")[zeile].attrib.get("HsigGeschw", 0.0)) if not ersatzsignal else 0.0
            if ersatzsignal or hsig_geschw != 0:
                # == 0 ohne Ersatzsignal koennen z.B. Flachkreuzungen sein
                min_geschw = geschw_min(min_geschw, hsig_geschw)
            print(" - Hauptsignal{} {} {} an {} auf {} {} ({}) {}".format(
                ("+" if hat_zaehler else ""),
                colored(signal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
                colored(signal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),
                rp,
                ("Zeile" if not ersatzsignal else (colored("Ersatzsignal", 'grey', attrs=['underline']) + 'zeile')),
                zeile,
                colored(str_geschw(hsig_geschw), 'red', attrs=['bold']),
                get_signalbild_fuer_zeile(signal, zeile, ersatzsignal),
            ), file=out)

            for modul, el, ri, schliessen in bue[rp]:
                if schliessen:
                    hat_bue = True
                    print("   - " + colored("!!! Bue schliessen an {}".format(str_el_ri(modul, el, ri)), 'red', attrs=['bold']), file=out)
            for modul, el, ri, schliessen in bue[rp]:
                if not schliessen:
                    hat_bue = True
                    print("   - " + colored("Bue oeffnen", 'green') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
            del bue[rp]

            if args.hsig_ausserhalb_fahrstrasse != 'ignorieren' and \
                    rp.el_r() not in elemente and \
                    (gegen(rp.el_r()) not in elemente or int(signal.attrib.get("SignalFlags", 0)) & 1 == 0):
                print("   - " + colored("!!! Hauptsignal ausserhalb der Fahrstrasse", 'red', attrs=['bold']), file=out)
                print_out = True

            ksig = signal.find("./KoppelSignal")
            indent = 2
            while ksig is not None:
                rp = get_refpunkt(get_modul_aus_dateiknoten(ksig, rp.modul), int(ksig.attrib.get("ReferenzNr", 0)))
                if not rp.valid():
                    print("{} - ".format(" " * indent) + colored("Koppelsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul_kurz()), 'white', 'on_red'), file=out)
                    break
                koppelsignal = rp.signal()
                if koppelsignal is None:
                    print("{} - ".format(" " * indent) + colored("Koppelsignal-Referenz mit fehlendem Signal an {} (Referenznummer {})".format(rp, rp.refnr), 'white', 'on_red'), file=out)
                    break
                hat_zaehler = hat_zaehler or int(koppelsignal.attrib.get("SignalFlags", 0)) & 8 != 0
                hsig_begriffe = koppelsignal.findall("./HsigBegriff")
                if zeile >= len(hsig_begriffe):
                    print("{} - ".format(" " * indent) + colored("Koppelsignal hat nicht genuegend Zeilen an {} (Referenznummer {})".format(rp, rp.refnr), 'white', 'on_red'), file=out)
                    break
                print("{} - Koppelsignal{} {} {} an {} auf Zeile {} ({}) {}".format(
                    " " * indent,
                    ("+" if int(koppelsignal.attrib.get("SignalFlags", 0)) & 8 != 0 else ""),
                    colored(koppelsignal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
                    colored(koppelsignal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),
                    rp,
                    zeile,
                    colored(str_geschw(float(hsig_begriffe[zeile].attrib.get("HsigGeschw", 0.0))), 'red', attrs=['bold']),
                    get_signalbild_fuer_zeile(koppelsignal, zeile, ersatzsignal),
                ), file=out)
                indent += 2
                ksig = koppelsignal.find("./KoppelSignal")

            if hat_bue and not hat_zaehler:
                print("   - " + colored("!!! Kein Signal mit Bue-Zaehler in der Koppelungskette", 'red', attrs=['bold']), file=out)

        for sig in f.findall("./FahrstrVSignal"):
            rp = get_refpunkt(get_modul_aus_dateiknoten(sig), int(sig.attrib.get("Ref", 0)))
            if not rp.valid():
                print(" - " + colored("Vorsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul_kurz()), 'white', 'on_red'), file=out)
                continue
            signal = rp.signal()
            spalte = int(sig.attrib.get("FahrstrSignalSpalte", 0))
            try:
                vsig_geschw = float(signal.findall("./VsigBegriff")[spalte].attrib.get("VsigGeschw", 0.0))
            except IndexError:
                print(" - Vorsignal {} {} an {} auf Spalte {} ({})".format(
                    colored(signal.attrib.get("NameBetriebsstelle", "?"), 'cyan'),
                    colored(signal.attrib.get("Signalname", "?"), 'cyan', attrs=['bold']),
                    rp,
                    spalte,
                    colored('ungueltige Spaltennummer', 'white', 'on_red'),
                ), file=out)
                continue

            alarm = ''
            if args.vsig_geschw != 'ignorieren' and vsig_geschw != -2.0 and geschw_kleiner(min_geschw, vsig_geschw):
                alarm = colored(" !!!!", 'red', attrs=['bold'])
                print_out = True

            print(" - Vorsignal {} {} an {} auf Spalte {} ({}) {}{}".format(
                colored(signal.attrib.get("NameBetriebsstelle", "?"), 'cyan'),
                colored(signal.attrib.get("Signalname", "?"), 'cyan', attrs=['bold']),
                rp,
                spalte,
                colored(str_geschw(vsig_geschw), 'green', attrs=['bold']),
                get_signalbild_fuer_spalte(signal, spalte),
                alarm
            ), file=out)

            if alarm != '' and args.vsig_geschw == 'ausgeben_exkl':
                print("   - Signal-Frames:", file=out)
                for sigframe in signal.findall("./SignalFrame/Datei"):
                    dateiname = sigframe.attrib.get("Dateiname", "")
                    print("     - {} {}".format(dateiname, ", ".join(get_animationen(dateiname))), file=out)
                print("   - Hsig-Geschwindigkeiten: {}".format(", ".join(map(str_geschw, [float(n.attrib.get("HsigGeschw", 0)) for n in signal.findall("./HsigBegriff")]))), file=out)
                print("   - Vsig-Geschwindigkeiten: {}".format(", ".join(map(str_geschw, [float(n.attrib.get("VsigGeschw", 0)) for n in signal.findall("./VsigBegriff")]))), file=out)

        if args.bue:
            for rp, values in bue.items():
                signal = rp.signal()
                hat_zaehler = int(signal.attrib.get("SignalFlags", 0)) & 8 != 0

                print(" - Bahnuebergang{} {} {} an {}".format(
                    ("+" if hat_zaehler else ""),
                    colored(signal.attrib.get("NameBetriebsstelle", "?"), 'green'),
                    colored(signal.attrib.get("Signalname", "?"), 'green', attrs=['bold']),
                    rp,
                ), file=out)

                hat_schliessen = False
                for modul, el, ri, schliessen in values:
                    if schliessen:
                        hat_schliessen = True
                        print("   - " + colored("Bue schliessen", 'green') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
                if not hat_schliessen:
                    print("   - " + colored("!!! Kein Schliessen-Ereignis in der Fahrstrasse", 'red', attrs=['bold']), file=out)

                hat_oeffnen = False
                for modul, el, ri, schliessen in values:
                    if not schliessen:
                        hat_oeffnen = True
                        print("   - " + colored("Bue oeffnen", 'green') + " an {}".format(str_el_ri(modul, el, ri)), file=out)
                if not hat_oeffnen:
                    print("   - " + colored("!!! Kein Oeffnen-Ereignis in der Fahrstrasse", 'red', attrs=['bold']), file=out)

                ksig = signal.find("./KoppelSignal")
                indent = 2
                while ksig is not None:
                    rp = get_refpunkt(get_modul_aus_dateiknoten(ksig, rp.modul), int(ksig.attrib.get("ReferenzNr", 0)))
                    if not rp.valid():
                        print("{} - ".format(" " * indent) + colored("Koppelsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul), 'white', 'on_red'), file=out)
                        break
                    koppelsignal = rp.signal()
                    if koppelsignal is None:
                        print("{} - ".format(" " * indent) + colored("Koppelsignal-Referenz mit fehlendem Signal an {} (Referenznummer {})".format(rp, rp.refnr), 'white', 'on_red'), file=out)
                        break
                    hat_zaehler = hat_zaehler or int(koppelsignal.attrib.get("SignalFlags", 0)) & 8 != 0
                    print("{} - Koppelsignal{} {} {} an {}".format(
                        " " * indent,
                        ("+" if int(koppelsignal.attrib.get("SignalFlags", 0)) & 8 != 0 else ""),
                        colored(koppelsignal.attrib.get("NameBetriebsstelle", "?"), 'green'),
                        colored(koppelsignal.attrib.get("Signalname", "?"), 'green', attrs=['bold']),
                        rp,
                    ), file=out)
                    indent += 2
                    ksig = koppelsignal.find("./KoppelSignal")

                if not hat_zaehler:
                    print("   - " + colored("!!! Kein Signal mit Bue-Zaehler in der Koppelungskette", 'red', attrs=['bold']), file=out)

        if args.register:
            reg_strs = []
            for reg in f.findall("./FahrstrRegister"):
                rp = get_refpunkt(get_modul_aus_dateiknoten(reg), int(reg.attrib.get("Ref", 0)))
                if not rp.valid():
                    reg_strs.append(colored("Register mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul_kurz()), 'white', 'on_red'))
                    continue
                richtung = rp.element.find("./Info" + ("Norm" if rp.richtung == NORM else "Gegen") + "Richtung")
                regnr = richtung.attrib.get("Reg", 0)
                reg_strs.append("{}{}".format(regnr, "" if rp.modul == dieses_modul else ("[" + rp.modul_kurz() + "]")))

            print(" - Register: {}".format(", ".join(reg_strs)), file=out)

        if args.weichen:
            for weiche in f.findall("./FahrstrWeiche"):
                rp = get_refpunkt(get_modul_aus_dateiknoten(weiche), int(weiche.attrib.get("Ref", 0)))
                if not rp.valid():
                    print(colored("Weiche mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul_kurz()), 'white', 'on_red'), file=out)
                    continue
                print(" - Weiche an {} auf Nachfolger {}".format(rp, weiche.attrib.get("FahrstrWeichenlage", 0)), file=out)

        if print_out:
            out.seek(0)
            print(out.read())
