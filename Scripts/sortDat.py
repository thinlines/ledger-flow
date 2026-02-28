#!/usr/bin/python

import sys
import re

myDict = {}

directive_re = re.compile("^[\w]")


with open(sys.argv[1]) as f:
    lines = f.readlines()
    for line in lines:
        match = directive_re.match(line)
        if match:
            key = match.string.strip()
            try:
                myDict[key]
            except KeyError:
                myDict[key] = []
                continue
        else:
            val = line.strip()
            myDict[key].append(val)

for key in sorted(myDict.keys()):
    print(key)
    for val in sorted(myDict[key]):
        print(" " * 4 + val)
