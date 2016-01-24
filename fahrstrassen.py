#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import sys
import os
import io
from collections import namedtuple
from termcolor import colored

import logging
logging.basicConfig(level = logging.DEBUG)

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

class RefPunkt(object):
    def __init__(self, modul, refnr, element, richtung):
        self.modul = modul
        self.refnr = refnr
        self.element = element
        self.richtung = richtung

    def __repr__(self):
        global dieses_modul
        return "Element {}{}{}".format(
            self.element.attrib.get("Nr", "0"),
            'n' if self.richtung == "Norm" else 'g',
            "" if self.modul == dieses_modul else "[{}]".format(os.path.basename(self.modul.replace('\\', os.sep))),
        )

    def valid(self):
        return self.element is not None

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

def get_zusi_relpath(realpath):
    if not os.path.isabs(realpath):
        realpath = os.path.abspath(realpath)
    return normalize_zusi_relpath(os.path.relpath(realpath, os.environ['ZUSI3_DATAPATH']))

def get_abspath(zusi_relpath):
    return path_insensitive(os.path.join(os.environ['ZUSI3_DATAPATH'], zusi_relpath.lstrip('\\').strip().replace('\\', os.sep)))

# {fehlendes Modul}
missing = set()

# Modul -> (Referenznummer -> (<StrElement>-Knoten, {"Norm", "Gegen"}))
referenzpunkte = dict()

# Modul -> [<Fahrstrasse>-Knoten]
fahrstrassen = dict()

def lade_modul(zusi_relpath):
    tree = ET.parse(get_abspath(zusi_relpath))
    # Elementnummer -> <StrElement>-Knoten
    streckenelemente = dict(
        (int(s.attrib.get("Nr", 0)), s)
        for s in tree.findall("./Strecke/StrElement")
    )
    referenzpunkte[zusi_relpath] = dict(
        (int(r.attrib.get("ReferenzNr", 0)), (streckenelemente[int(r.attrib.get("StrElement", 0))], "Norm" if int(r.attrib.get("StrNorm", 0)) == 1 else "Gegen"))
        for r in tree.findall("./Strecke/ReferenzElemente")
        if int(r.attrib.get("StrElement", 0)) in streckenelemente
    )
    fahrstrassen[zusi_relpath] = tree.findall("./Strecke/Fahrstrasse")

dieses_modul = get_zusi_relpath(sys.argv[1])
logging.debug("Dieses Modul: {} -> {}".format(sys.argv[1], dieses_modul))

lade_modul(dieses_modul)
logging.debug("{} Referenzpunkt(e), {} Fahrstrasse(n)".format(len(referenzpunkte[dieses_modul]), len(fahrstrassen[dieses_modul])))

def get_refpunkt(modul, nummer):
    if modul not in referenzpunkte:
        modul = normalize_zusi_relpath(modul)
        if modul in missing:
            return RefPunkt(modul, nummer, None, "")
        try:
            lade_modul(modul)
        except FileNotFoundError:
            missing.add(modul)
            return RefPunkt(modul, nummer, None, "")

    try:
        (element, richtung) = referenzpunkte[modul][nummer]
    except KeyError:
        return RefPunkt(modul, nummer, None, "")
    return RefPunkt(modul, nummer, element, richtung)

# Sucht Knoten ./Datei und liefert Modul zurueck (leerer String oder nicht vorhandener Knoten = dieses Modul)
def get_modul_aus_dateiknoten(knoten):
    datei = sig.find("./Datei")
    if datei is not None:
        return normalize_zusi_relpath(datei.attrib.get("Dateiname", dieses_modul))
    return dieses_modul

# -----

# Signal-LS3 -> [Animationsname]
animationen = dict()

def get_animationen(signal_ls3_relpath):
    signal_ls3_relpath = normalize_zusi_relpath(signal_ls3_relpath)
    if signal_ls3_relpath not in animationen:
        tree = ET.parse(get_abspath(signal_ls3_relpath))
        animationen[signal_ls3_relpath] = [n.attrib.get("AniBeschreibung", "?") for n in tree.findall("./Landschaft/Animation")]
    return animationen[signal_ls3_relpath]

def get_signalbild(signal, signalbild_id):
    idx = 0
    result = []
    for sigframe in signal.findall("./SignalFrame/Datei"):
        animationen = get_animationen(sigframe.attrib["Dateiname"])
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
    zeilen = signal.findall("./HsigBegriff")
    anz_spalten = len(signal.findall("./VsigBegriff"))
    matrix = signal.findall("./MatrixEintrag")

    ereignisse = None

    for idx, zeile in enumerate(zeilen):
        # Betrachte nur Zeilen fuer Zugfahrten mit Geschwindigkeit > 0,
        # sonst kann im H/V-System das Signalbild nicht bestimmt werden
        # (bei Hp0 ist Vorsignal dunkel)
        if float(zeile.attrib.get("HsigGeschw", 0.0)) != 0.0 and int(zeile.attrib.get("FahrstrTyp", 0)) & 4 != 0:
            eintrag = matrix[idx * anz_spalten + spalte]
            signalbild_id &= int(eintrag.attrib.get("Signalbild", 0))
            eintrag_ereignisse = set(int(e.attrib.get("Er", 0)) for e in eintrag.findall("./Ereignis"))
            if ereignisse is None:
                ereignisse = eintrag_ereignisse.copy()
            else:
                ereignisse = ereignisse.intersection(eintrag_ereignisse)

    return get_signalbild(signal, signalbild_id) + ("" if ereignisse is None or len(ereignisse) == 0 else (" + " + " + ".join(str(e) for e in ereignisse)))

def get_signalbild_fuer_zeile(signal, zeile, ersatzsignal):
    if ersatzsignal:
        return "?"

    signalbild_id = all_ones
    anz_spalten = len(signal.findall("./VsigBegriff"))
    matrix = signal.findall("./MatrixEintrag")

    for i in range(0, anz_spalten):
        signalbild_id &= int(matrix[zeile * anz_spalten + i].attrib.get("Signalbild", 0))

    return get_signalbild(signal, signalbild_id)

for f in fahrstrassen[dieses_modul]:
    print_out = False
    with io.StringIO() as out:
        print("\nFahrstrasse {} {}".format(f.attrib.get("FahrstrTyp", "?"), colored(f.attrib.get("FahrstrName", "?"), 'grey', attrs=['bold'])), file=out)

        min_geschw = -1

        for sig in f.findall("./FahrstrSignal"):
            rp = get_refpunkt(get_modul_aus_dateiknoten(sig), int(sig.attrib.get("Ref", 0)))
            if not rp.valid():
                print(" - " + colored("Hauptsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul), 'white', 'on_red'), file=out)
                continue
            signal = rp.element.find("./Info" + rp.richtung + "Richtung/Signal")
            ersatzsignal = int(sig.attrib.get("FahrstrSignalErsatzsignal", 0)) == 1
            zeile = int(sig.attrib.get("FahrstrSignalZeile", 0))
            hsig_geschw = float(signal.findall("./HsigBegriff")[zeile].attrib.get("HsigGeschw", 0.0)) if not ersatzsignal else 0.0
            if ersatzsignal or hsig_geschw != 0:
                # == 0 ohne Ersatzsignal koennen z.B. Flachkreuzungen sein
                min_geschw = geschw_min(min_geschw, hsig_geschw)
            print(" - Hauptsignal {} {} an {} auf {} {} ({}) {}".format(
                colored(signal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
                colored(signal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),
                rp,
                ("Zeile" if not ersatzsignal else (colored("Ersatzsignal", 'grey', attrs=['underline']) + 'zeile')),
                zeile,
                colored(str_geschw(hsig_geschw), 'red', attrs=['bold']),
                get_signalbild_fuer_zeile(signal, zeile, ersatzsignal),
            ), file=out)

            ksig = signal.find("./KoppelSignal")
            indent = 2
            while ksig is not None:
                rp = get_refpunkt(get_modul_aus_dateiknoten(ksig), int(ksig.attrib.get("ReferenzNr", 0)))
                if not rp.valid():
                    print("{} - ".format(" " * indent) + colored("Koppelsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul), 'white', 'on_red'), file=out)
                    break
                koppelsignal = rp.element.find("./Info" + rp.richtung + "Richtung/Signal")
                if koppelsignal is None:
                    print("{} - ".format(" " * indent) + colored("Koppelsignal-Referenz mit fehlendem Signal an {} (Referenznummer {})".format(rp, rp.refnr, rp.modul), 'white', 'on_red'), file=out)
                    break
                print("{} - Koppelsignal {} {} an {} auf Zeile {} ({}) {}".format(
                    " " * indent,
                    colored(koppelsignal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
                    colored(koppelsignal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),
                    rp,
                    zeile,
                    colored(str_geschw(float(koppelsignal.findall("./HsigBegriff")[zeile].attrib.get("HsigGeschw", 0.0))), 'red', attrs=['bold']),
                    get_signalbild_fuer_zeile(koppelsignal, zeile, ersatzsignal),
                ), file=out)
                indent += 2
                ksig = koppelsignal.find("./KoppelSignal")

        for sig in f.findall("./FahrstrVSignal"):
            rp = get_refpunkt(get_modul_aus_dateiknoten(sig), int(sig.attrib.get("Ref", 0)))
            if not rp.valid():
                print(" - " + colored("Vorsignal mit nicht aufloesbarer Referenz {} in Modul {}".format(rp.refnr, rp.modul), 'white', 'on_red'), file=out)
                continue
            signal = rp.element.find("./Info" + rp.richtung + "Richtung/Signal")
            spalte = int(sig.attrib.get("FahrstrSignalSpalte", 0))
            vsig_geschw = float(signal.findall("./VsigBegriff")[spalte].attrib.get("VsigGeschw", 0.0))
            alarm = vsig_geschw != -2.0 and geschw_kleiner(min_geschw, vsig_geschw)
            print_out |= alarm
            print(" - Vorsignal {} {} an {} auf Spalte {} ({}) {} {}".format(
                colored(signal.attrib.get("NameBetriebsstelle", "?"), 'cyan'),
                colored(signal.attrib.get("Signalname", "?"), 'cyan', attrs=['bold']),
                rp,
                spalte,
                colored(str_geschw(vsig_geschw), 'green', attrs=['bold']),
                get_signalbild_fuer_spalte(signal, spalte),
                colored("!!!!", 'red', attrs=['bold']) if alarm else "",
            ), file=out)
            if alarm:
                print("   - Signal-Frames:", file=out)
                for sigframe in signal.findall("./SignalFrame/Datei"):
                    dateiname = sigframe.attrib.get("Dateiname", "")
                    print("     - {} {}".format(dateiname, ", ".join(get_animationen(dateiname))), file=out)
                print("   - Hsig-Geschwindigkeiten: {}".format(", ".join(map(str_geschw, [float(n.attrib.get("HsigGeschw", 0)) for n in signal.findall("./HsigBegriff")]))), file=out)
                print("   - Vsig-Geschwindigkeiten: {}".format(", ".join(map(str_geschw, [float(n.attrib.get("VsigGeschw", 0)) for n in signal.findall("./VsigBegriff")]))), file=out)

        if (print_out):
            out.seek(0)
            print(out.read())
