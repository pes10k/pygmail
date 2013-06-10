"""Recent (2.6+) versions of the email library that comes with python
added in the ability to parse partially complete email messages, by reading
them line by line. This slows down pygmail's functionality, where we're sure
to only be reading full message bodies.  The below monkey-patches result
in a significant, 20%+ speed improvement by only parsing full email messages"""


import email.feedparser
import email.parser


# Replace the feedparser's parse string functionality to read the whole
# string in at once, instead of 8K at a time
def parsestr(self, text, headersonly=False):
    feed_parser = email.feedparser.FeedParser(self._class)

    if headersonly:
        feed_parser._set_headersonly()

    feed_parser.feed(text)
    return feed_parser.close()

email.parser.Parser.parsestr = parsestr


class BufferedSubFile(object):
    def __init__(self):
        self.lines = []
        self.index = -1
        self.num_lines = 0

    def push_eof_matcher(self, pred):
        pass

    def pop_eof_matcher(self):
        pass

    def close(self):
        pass

    def readline(self):
        try:
            self.index += 1
            return self.lines[self.index]
        except IndexError:
            return ''

    def unreadline(self, line):
        self.index -= 1

    def push(self, data):
        """Push some new data into this object."""
        self.lines = data.splitlines(True)
        self.num_lines = len(self.lines)
        self.index = -1

    def pushlines(self, lines):
        pass

    def is_closed(self):
        pass

    def __iter__(self):
        return self

    def next(self):
        try:
            self.index += 1
            return self.lines[self.index]
        except IndexError:
            raise StopIteration

email.feedparser.BufferedSubFile = BufferedSubFile
