#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import sys
from termcolor import colored

tree = ET.parse(sys.argv[1])

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

# HACK
str_dateiname = tree.find("./Strecke/Datei").attrib["Dateiname"].upper().replace(".LS3", ".ST3")

streckenelemente = dict(
        (int(s.attrib.get("Nr", 0)), s)
        for s in tree.findall("./Strecke/StrElement")
    )

referenzpunkte = dict(
        (int(r.attrib.get("ReferenzNr", 0)), (streckenelemente[int(r.attrib.get("StrElement", 0))], "Norm" if int(r.attrib.get("StrNorm", 0)) == 1 else "Gegen"))
        for r in tree.findall("./Strecke/ReferenzElemente")
        if int(r.attrib.get("StrElement", 0)) in streckenelemente
    )

for f in tree.findall("./Strecke/Fahrstrasse"):
    print("\nFahrstrasse {} {}".format(f.attrib.get("FahrstrTyp", "?"), colored(f.attrib.get("FahrstrName", "?"), 'grey', attrs=['bold'])))

    min_geschw = -1

    for sig in f.findall("./FahrstrSignal"):
        datei = sig.find("./Datei")
        if datei is not None:
            dateiname = datei.attrib.get("Dateiname", "")
            if dateiname != "" and dateiname.upper() != str_dateiname:
                print(colored(" - Hauptsignal in Modul {}".format(dateiname), 'grey'))
                continue
        (element, richtung) = referenzpunkte[int(sig.attrib.get("Ref", 0))]
        signal = element.find("./Info" + richtung + "Richtung/Signal")
        ersatzsignal = int(sig.attrib.get("FahrstrSignalErsatzsignal", 0)) == 1
        zeile = int(sig.attrib.get("FahrstrSignalZeile", 0))
        hsig_geschw = float(signal.findall("./HsigBegriff")[zeile].attrib.get("HsigGeschw", 0.0)) if not ersatzsignal else 0.0
        if ersatzsignal or hsig_geschw != 0:
            # == 0 ohne Ersatzsignal koennen z.B. Flachkreuzungen sein
            min_geschw = geschw_min(min_geschw, hsig_geschw)
        print(" - Hauptsignal {} {} an Element {} {} auf {} {} ({})".format(
            colored(signal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
            colored(signal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),

            element.attrib.get("Nr", 0),
            richtung,

            ("Zeile" if not ersatzsignal else (colored("Ersatzsignal", 'grey', attrs=['underline']) + 'zeile')),
            zeile,
            colored(str_geschw(hsig_geschw), 'red', attrs=['bold']),
        ))

        ksig = signal.find("./KoppelSignal")
        (element_alt, richtung_alt) = (None, None)
        indent = 2
        while ksig is not None:
            datei = ksig.find("./Datei")
            if datei is not None:
                dateiname = datei.attrib.get("Dateiname", "")
                if dateiname != "" and dateiname.upper() != str_dateiname:
                    print(colored("   - Koppelsignal in Modul {}".format(dateiname), 'grey'))
                    break
            try:
                (element, richtung) = referenzpunkte[int(ksig.attrib.get("ReferenzNr", 0))]
            except KeyError:
                print(colored("{} - Ungueltige Koppelsignal-Referenz".format(" " * indent), 'red', attrs=['bold']))
                break
            if (element, richtung) == (element_alt, richtung_alt):
                print(colored("{} - Zirkelbezug in Koppelsignal".format(" " * indent)), 'red', attrs=['bold'])
                break
            koppelsignal = element.find("./Info" + richtung + "Richtung/Signal")
            print("{} - Koppelsignal {} {} an Element {} {} auf Zeile {} ({})".format(
                " " * indent,
                colored(koppelsignal.attrib.get("NameBetriebsstelle", "?"), 'blue'),
                colored(koppelsignal.attrib.get("Signalname", "?"), 'blue', attrs=['bold']),

                element.attrib.get("Nr", 0),
                richtung,

                zeile,
                colored(str_geschw(float(koppelsignal.findall("./HsigBegriff")[zeile].attrib.get("HsigGeschw", 0.0))), 'red', attrs=['bold']),
            ))
            indent += 2
            ksig = koppelsignal.find("./KoppelSignal")

    for sig in f.findall("./FahrstrVSignal"):
        datei = sig.find("./Datei")
        if datei is not None:
            dateiname = datei.attrib.get("Dateiname", "")
            if dateiname != "" and dateiname.upper() != str_dateiname:
                print(colored(" - Vorsignal in Modul {}".format(dateiname), 'grey'))
                continue
        (element, richtung) = referenzpunkte[int(sig.attrib.get("Ref", 0))]
        signal = element.find("./Info" + richtung + "Richtung/Signal")
        spalte = int(sig.attrib.get("FahrstrSignalSpalte", 0))
        vsig_geschw = float(signal.findall("./VsigBegriff")[spalte].attrib.get("VsigGeschw", 0.0))
        print(" - Vorsignal {} {} an Element {} {} auf Spalte {} ({}) {}".format(
            colored(signal.attrib.get("NameBetriebsstelle", "?"), 'cyan'),
            colored(signal.attrib.get("Signalname", "?"), 'cyan', attrs=['bold']),

            element.attrib.get("Nr", 0),
            richtung,

            spalte,
            colored(str_geschw(vsig_geschw), 'green', attrs=['bold']),
            colored("!!!!", 'red', attrs=['bold']) if geschw_kleiner(min_geschw, vsig_geschw) else "",
        ))
