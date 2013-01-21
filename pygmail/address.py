from email.header import decode_header
from email.utils import parseaddr


class Address(object):

    def __init__(self, address):
        self.raw_address = address

    def __key(self):
        return (self.name, self.address)

    def __eq__(self, other):
        return self.__key() == other.__key()

    def __cmp__(self, other):
        return cmp(self.__key(), other.__key())

    def __hash__(self):
        return hash(self.__key())

    def __str__(self):
        if self.name:
            return "%s <%s>" % (self.name, self.address)
        else:
            return self.address

    @property
    def name(self):
        if not hasattr(self, '_name'):
            self.parse_address()
        return self._name

    @property
    def address(self):
        if not hasattr(self, '_address'):
            self.parse_address()
        return self._address

    def parse_address(self):
        name_encoded, self._address = parseaddr(self.raw_address)
        decoded_name, decoded_encoding = decode_header(name_encoded)[0]
        if not decoded_encoding:
            self._name = unicode(decoded_name, 'ascii', errors='replace')
        elif decoded_encoding == "utf-8":
            self._name = decoded_name
        else:
            self._name = unicode(decoded_name, decoded_encoding, errors='replace')
