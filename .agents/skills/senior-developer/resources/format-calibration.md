# Format and Protocol Calibration

When the code you're writing touches a file format, protocol, schema, or any external string convention (date formats, CSV dialects, API envelopes, ledger output, hash shapes, etc.), the production code reads from a wider universe than your fixtures. Synthetic fixtures are a *guess* about production shape; tests built only on guessed fixtures can pass while the production code silently fails on real input.

Before writing a fixture for format-handling code:

- **Sample one real example** from `workspace/`, recent imports, live API responses, or wherever the production code actually reads from. A 60-second `Read` is enough.
- **Compare the real sample's shape against what you were about to type.** Date format, casing, whitespace, optional fields, header conventions, separator characters. Match what's actually there, not what's natural to type in Python.
- **The fixture stays synthetic and committed; the real sample stays uncommitted.** This is not ingesting user data into tests — it is calibrating the synthetic model against the real one.
- **If you cannot find a real example, mark the fixture explicitly** with a comment like `# UNCALIBRATED — assumed format; no real example available`. That tag tells the next reader the fixture is unverified.

The cost is one read of a real file. The bug class it prevents is structural — fixtures that match the developer's mental picture but not production's actual shape, and tests that pass on fictional data while production breaks.
