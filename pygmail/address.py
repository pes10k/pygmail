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

    def __unicode__(self):
        if self.name:
            return u"%s <%s>" % (self.name, self.address)
        else:
            return self.address

    def __str__(self):
        return str(self.__unicode__())

    @property
    def name(self):
        try:
            return self._name
        except AttributeError:
            self.parse_address()
            return self._name

    @property
    def address(self):
        try:
            return self._address
        except AttributeError:
            self.parse_address()
            return self._address

    def parse_address(self):
        if (isinstance(self.raw_address, list) or isinstance(self.raw_address, tuple)) and len(self.raw_address) == 2:
            name_encoded, self._address = self.raw_address
        else:
            name_encoded, self._address = parseaddr(self.raw_address[0])
        self._address = self._address.strip("<>")
        try:
            decoded_name, decoded_encoding = decode_header(name_encoded)[0]
            if not decoded_encoding:
                self._name = unicode(decoded_name, 'ascii', errors='replace')
            else:
                self._name = unicode(decoded_name, decoded_encoding,
                                     errors='replace')
        except Exception as e:
            self._name = u''
            self.encoding_error = e
