Don't include coauthor lines in commit messages.

When coding: the goal is as few modules as possible. They should have the simplest possible interfaces that hide unimportant implementation details from callers. This makes the modules easier to use and test. Call this out and be critical of your own implementations; always ask, "could this interface be simpler?"