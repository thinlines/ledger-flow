#!/usr/bin/python

import sys
import re
import csv

payeeptn = re.compile("^payee[ \t]+")
aliasptn = re.compile("^[ \t]+alias[ \t]+")
aliases = dict()

with open(sys.argv[1]) as f:
    file = f.readlines()
    for line in file:
        match = payeeptn.match(line)
        if match:
            payee = line[match.end():].strip()
            try:
                aliases[payee]
            except KeyError:
                aliases[payee] = []
            continue
        match = aliasptn.match(line)
        if match:
            alias = line[match.end():].strip()
            aliases[payee].append(alias)

fieldnames = ["payee", "alias"]
writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames,
                        quoting=csv.QUOTE_MINIMAL)
writer.writeheader()
for payee in sorted([str(key) for key in aliases.keys()]):
    for alias in aliases[payee]:
        writer.writerow({"payee": payee, "alias": alias})
