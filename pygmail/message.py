import email
import re
import email.utils
import email.header as eh
import email.encoders as ENC
import email.charset
import time
import pygmail.errors
from imaplib import Internaldate2tuple, ParseFlags
from base64 import b64decode
from datetime import datetime
from quopri import encodestring, decodestring
from email.parser import HeaderParser
from email.Iterators import typed_subpart_iterator
from pygmail.address import Address
from pygmail.utilities import extract_data, extract_first_bodystructure, parse, ParseError, _cmd_in, _cmd_cb, _cmd, _log
from pygmail.errors import is_encoding_error, check_for_response_error
from hashlib import sha256


# A regular expression used for extracting metadata information out
# of the raw IMAP returned string.
METADATA_PATTERN = re.compile(r'(\d*) \(X-GM-MSGID (\d*) X-GM-LABELS \((.*)\) UID (\d*) INTERNALDATE "(.*?)"')

METADATA_TEASER_PATTERN = re.compile(r'(\d*) \(X-GM-MSGID (\d*) X-GM-LABELS \((.*)\) UID (\d*) INTERNALDATE "(.*?)"')

BODY_STRUCTRUE = re.compile(r'BODYSTRUCTURE \((.*?)\) BODY\[HEADER\]')
CHARSET_EXTRACTOR = re.compile(r'\("charset" "(.*?)"')
HEADER_PARSER = HeaderParser()
BOUNDARY_EXTRACTOR = re.compile(r'\("BOUNDARY" "(.*?)"\)', re.I)
SECTION_HEADERS_ENDING = re.compile(r'\n\n|\r\r|\r\n\r\n', re.M)
ENCODING_EXTRACTOR = re.compile(r'7bit|8bit|base64|quoted-printable')


def extract_first_subsection(message, boundary):
    """Extracts the first instance of an embeded, multipart email message,
    described / bounded by the given boundry string.  None of this will make
    any sense without a sickening understanding of RFC822

    Args:
        message  -- The partial body of an RFC822 email message as a string
        boundary -- The bounds of a multipart email message

    Returns:
        The first subpart instance, if its availabe / can be found.  Otherwise,
        returns the given message text unchanged
    """
    try:
        full_boundary = "--" + boundary
        boundary_length = len(full_boundary) + 1
        first_instance = message.index(full_boundary)
        next_instance = message.index(full_boundary, first_instance + boundary_length)
        message_section = message[first_instance + boundary_length:next_instance + 1].strip()
        header_matches = SECTION_HEADERS_ENDING.search(message_section)
        if not header_matches:
            return message
        else:
            return message_section[header_matches.start() + len(header_matches.group(0)):].strip()
    except ValueError:
        return message


def message_part_charset(part, message):
    """Get the charset of the a part of the message"""
    message_part_charset = part.get_content_charset() or part.get_charset()
    if not message_part_charset:
        message_part_charset = message.get_content_charset() or message.get_charset()
    if not message_part_charset:
        return "ascii"
    else:
        if isinstance(message_part_charset, email.charset.Charset):
            return message_part_charset.get_output_charset() or 'utf-8'
        else:
            # It is sometimes possible for the encoding section to include
            # information we're not interested in, such as mime verison.
            # So, we strip that off here if its included
            return message_part_charset.split(" ")[0]


def message_in_list(message, message_list):
    """Checks to see if a Gmail message is represented in a list

    Checks to see if a list contains a message object representing the same
    message as another provided message object.  Since its possible for two
    different objects to represent the same email message, we can't rely
    on list.__contains__() / in operator.  This helper function does the
    effective same thing.

    Arguments:
        message      -- a pygmail.message.Message object, reperesenting an email
                        message
        message_list -- a python list, containg zero or more
                        pygmail.message.Message objects

    Returns:
        True if the list contains an object representing the same message
        the passed 'message' object represents, and otherwise False.
    """
    for a_message in message_list:
        if message == a_message:
            return True
    return False


def utf8_encode_message_part(message_part, message, default="ascii"):
    """Returns the payload of a part of an email, encoded as UTF-8

    Normalizes the text / contents of an email message to be UTF-8, regardless
    of its original encoding

    Arguments:
        message_part     -- a section of an email message
        default          -- the advertised encoding of the entire message
                            that this message part was a part of

    Returns:

        UnicodeDecodeError if there was a problem decoding the message
    """
    # If we've already decoded this part of the message in a normalized
    # UTF-8 version, we can short circuit the re-decoding process
    # and just return the cached version
    if hasattr(message_part, '_normalized'):
        return message_part._normalized

    payload = message_part.get_payload(decode=True)

    if isinstance(payload, unicode):
        message_part._orig_charset = "utf-8"
        return payload
    else:
        section_charset = message_part_charset(message_part, message)
        charset = section_charset or default

        # We want to normalize everything internally to be UTF-8,
        # so if this is the first time we converted the body of the message,
        # we need to make a note of what the original charset was, so
        # we can re-encode to its original charset if needed
        if not hasattr(message_part, '_orig_charset'):
            message_part._orig_charset = charset
            message_part.set_charset("utf-8")

        if charset and "utf-8" not in charset:
            try:
                normalized = unicode(payload, charset, errors='replace')
            except LookupError as error:
                return error
            except UnicodeDecodeError as error:
                return error
        elif charset == "utf-8":
            try:
                normalized = unicode(payload, "utf-8")
            except UnicodeDecodeError as error:
                return error
        else:
            try:
                normalized = unicode(payload, "ascii", errors='replace')
            except UnicodeDecodeError as error:
                return error

        message_part._normalized = normalized
        return normalized


class MessageBase(object):
    """A root class, containing some shared functionality between the full
    and message teaser instances"""
    def __init__(self, mailbox, metadata, headers, metadata_pattern):
        self.mailbox = mailbox
        self.account = mailbox.account
        self.conn = self.account.connection
        metadata_rs = metadata_pattern.match(metadata)

        if not metadata_rs:
            _log.error("Bad formatted metadata string")
            _log.error(metadata)

        self.id, self.gmail_id, labels, self.uid, internal_date = metadata_rs.groups()
        self.internal_date = Internaldate2tuple(metadata)

        self.flags = ParseFlags(metadata) or []
        self.labels_raw = labels

        ### First parse out the metadata about the email message
        self.headers = HEADER_PARSER.parsestr(headers)

        for attr, single_header in (('date', 'Date'), ('subject', 'Subject')):
            header_value = self.get_header(single_header)
            setattr(self, attr, header_value[0] if header_value else '')

        self.sender = self.get_header("From")
        self.to = self.get_header('To')
        self.cc = self.get_header("Cc")

        message_ids = self.get_header('Message-Id')
        if len(message_ids) == 0:
            self.message_id = None
        else:
            self.message_id = message_ids[0]

    def __eq__(self, other):
        """ Overrides equality operator to check by uid and mailbox name """
        return (isinstance(other, MessageBase) and
                self.uid == other.uid and
                self.mailbox.name == other.mailbox.name)

    def __str__(self):
        return "<Message %s: Message-ID: '%s'>" % (self.uid, self.message_id)

    def get_header(self, key):
        """Returns a unicode version of the requested header value, properly
        decoded

        Args:
            key -- the header value desired

        Return:
            A list or tuple of zero or more unicode values, describing the
            value stored in the header field
        """
        try:
            raw_headers = eh.decode_header(self.headers[key])
            header_values = []
            for value, encoding in raw_headers:
                header_encoding = encoding or 'ascii'
                unicode_header = unicode(value, header_encoding,
                                         errors='replace')
                header_values.append(unicode_header)
            if len(header_values) == 1 and header_values[0] == u'None':
                return ()
            else:
                return header_values
        except Exception:
            return ()

    @property
    def from_address(self):
        if not hasattr(self, '_from_address'):
            self._from_address = Address(self.sender)
        return self._from_address

    @property
    def to_address(self):
        if not hasattr(self, '_to_address'):
            self._to_address = Address(self.to)
        return self._to_address

    @property
    def labels(self):
        """Lazy parse the stored raw string of gmail labels, which is in
        gmail's combination of ASTRING, STRING and ATOM formats.  Occasionally
        the parser we're using here falls into an infinite loop, so this can
        throw a 'RuntimeError' exception.

        Returns:
            A list of X-GM-LABELS if we can parse them correctly, and otherwise
            None

        Raises:
            RuntimeError if there is an error parsing the labels (ie if the
            library we're using falls into an infinite loop)
        """
        try:
            return self._labels
        except AttributeError:
            try:
                self._labels = list(parse(self.labels_raw))
            except ParseError:
                self._labels = None
            return self._labels

    def is_read(self):
        """Checks to see if the message has been flaged as read

        Returns:
            True if the message is flagged as read, and otherwise False

        """
        return "\Seen" in self.flags

    def datetime(self):
        """Returns the date of when the message was sent

        Lazy-loads the date of when the message was sent (as a tuple)
        based on the string date/time advertised in the email header

        Returns:
            A tuple object representation of when the message was sent
        """
        if not hasattr(self, '_datetime'):
            self._datetime = email.utils.parsedate(self.date)
        return self._datetime

    def sent_datetime(self):
        """Returns a datetime object of when the message was sent

        Lazy-loads a datetime object representation of when the message
        was sent

        Returns:
            A datetime object
        """
        if not hasattr(self, "_sent_datetime"):
            date_parts = self.datetime()
            self._sent_datetime = datetime.fromtimestamp(time.mktime(date_parts)) if date_parts else None
        return self._sent_datetime

    def delete(self, trash_folder, callback=None):
        """Deletes the message from the IMAP server

        Args:
            trash_folder -- the name of the folder / label that is, in the
                            current account, the trash container

        Returns:
            True on success, and in all other instances an error object
        """
        @pygmail.errors.check_imap_response(callback)
        def _on_original_mailbox_reselected(imap_response):
            return _cmd(callback, True)

        @pygmail.errors.check_imap_state(callback)
        def _on_recevieved_connection_6(connection):
            return _cmd_cb(connection.select, _on_original_mailbox_reselected,
                           bool(callback), self.mailbox.name)

        @pygmail.errors.check_imap_response(callback)
        def _on_expunge_complete(imap_response):
            return _cmd_cb(self.conn, _on_recevieved_connection_6, bool(callback))

        @pygmail.errors.check_imap_state(callback)
        def _on_recevieved_connection_5(connection):
            return _cmd_cb(connection.expunge, _on_expunge_complete, bool(callback))

        @pygmail.errors.check_imap_response(callback)
        def _on_delete_complete(imap_response):
            return _cmd_cb(self.conn, _on_recevieved_connection_5, bool(callback))

        @pygmail.errors.check_imap_state(callback)
        def _on_received_connection_4(connection, deleted_uid):
            del self.num_tries
            return _cmd_cb(connection.uid, _on_delete_complete,
                           bool(callback), 'STORE', deleted_uid,
                           '+FLAGS', '\\Deleted')

        @pygmail.errors.check_imap_response(callback)
        def _on_search_for_message_complete(imap_response):
            data = extract_data(imap_response)

            # Its possible here that we've tried to select the message
            # we want to delete from the trash bin before google has
            # registered it there for us.  If our search attempt returned
            # a uid, then we're good to go and can continue.
            try:
                deleted_uid = data[0].split()[-1]
                cbp = dict(deleted_uid=deleted_uid)
                return _cmd_cb(self.conn, _on_received_connection_4,
                               bool(callback), callback_args=cbp)

            # If not though, we should wait a couple of seconds and try
            # again.  We'll do this a maximum of 5 times.  If we still
            # haven't had any luck at this point, we give up and return
            # False, indiciating we weren't able to delete the message
            # fully.
            except IndexError:
                self.num_tries += 1

                # If this is the 5th time we're trying to delete this
                # message, we're going to call it a loss and stop trying.
                # We do some minimal clean up and then just bail out
                # Otherwise, schedule another attempt in 2 seconds and
                # hope that gmail has updated its indexes by then
                if self.num_tries == 5:
                    del self.num_tries
                    if __debug__:
                        _log.error(u"Giving up trying to delete message {subject} - {id}".format(subject=self.subject, id=self.message_id))
                        _log.error("got response: {response}".format(response=str(imap_response)))
                    return _cmd(callback, False)
                else:
                    if __debug__:
                        _log.error("Try {num} to delete deleting message {subject} - {id} failed.  Waiting".format(num=self.num_tries, subject=self.subject, id=self.message_id))
                        _log.error("got response: {response}".format(response=str(imap_response)))
                    return _cmd_in(_on_trash_selected, 2, bool(callback), force_success=True)

        @pygmail.errors.check_imap_state(callback)
        def _on_received_connection_3(connection):
            return _cmd_cb(connection.uid, _on_search_for_message_complete,
                           bool(callback), 'search', None, 'X-GM-RAW',
                            '"rfc822msgid:{msg_id}"'.format(msg_id=self.message_id))

        def _on_trash_selected(imap_response, force_success=False):
            # It can take several attempts for the deleted message to show up
            # in the trash label / folder.  We'll try 5 times, waiting
            # two sec between each attempt
            if force_success:
                return _cmd_cb(self.conn, _on_received_connection_3, bool(callback))
            else:
                is_error = check_for_response_error(imap_response)
                if is_error:
                    return _cmd(callback, is_error)
                else:
                    return _cmd_cb(self.conn, _on_received_connection_3, bool(callback))

        @pygmail.errors.check_imap_state(callback)
        def _on_received_connection_2(connection):
            self.num_tries = 0
            return _cmd_cb(connection.select, _on_trash_selected, bool(callback), trash_folder)

        @pygmail.errors.check_imap_response(callback)
        def _on_message_moved(imap_response):
            return _cmd_cb(self.conn, _on_received_connection_2, bool(callback))

        @pygmail.errors.check_imap_state(callback)
        def _on_received_connection(connection):
            return _cmd_cb(connection.uid, _on_message_moved, bool(callback),
                           'COPY', self.uid, trash_folder)

        @pygmail.errors.check_imap_response(callback)
        def _on_mailbox_select(is_selected):
            return _cmd_cb(self.conn, _on_received_connection, bool(callback))

        return _cmd_cb(self.mailbox.select, _on_mailbox_select, bool(callback))


class MessageHeaders(MessageBase):
    """A message response from Gmail that contains just the headers of an email
    message (subject, to / from, etc).  This is what all mailbox level functions
    return by default"""

    def __init__(self, mailbox, metadata, headers):
        super(MessageHeaders, self).__init__(mailbox, metadata, headers, METADATA_PATTERN)

    def teaser(self, callback=None):
        """Fetches an abbreviated, teaser version of the message, containing
        just the text of the first text or html part of the message body
        """
        def _on_teaser_fetched(teaser):
            return _cmd(callback, teaser)

        return _cmd_cb(self.mailbox.fetch, _on_teaser_fetched, bool(callback), self.uid, teaser=True)

    def full_message(self, callback=None):
        """Fetches the full version of the message that this message is a teaser
        version of."""
        def _on_full_message_fetched(full_msg):
            return _cmd(callback, full_msg)

        return _cmd_cb(self.mailbox.fetch, _on_full_message_fetched, bool(callback), self.uid, full=True)


class MessageTeaser(MessageBase):
    """A simplfied, abbreviated version of an email message that only contains
    the first section of the email message.  This is intented to serve as
    a smaller, preview of the the message that can save the time of bringing
    down email attachments or other sections.

    Since this is just a subset of the message, no write operations are
    available.

    Instances of this class aren't intended to be constructed directly, but
    instead managed by the pygmail.mailbox.Message instances
    """
    def __init__(self, mailbox, metadata, headers, body):
        """

        Args:
            mailbox  -- Reference to the pygmail.mailbox.Mailbox object
                        representing the mailbox that this message was fetched
                        from
            metadata -- A string containing metadata about this teaser,
                        such as the message uid, gmail id, labels, etc.
            headers  -- The email headers of the message, including information
                        such as encoding type, the to and from addresses, etc.
            body     -- The body of the first section of the email message
        """
        super(MessageTeaser, self).__init__(mailbox, metadata, headers, METADATA_TEASER_PATTERN)

        self.charset = 'utf-8'
        self.encoding = '8bit'
        body_structure = None
        first_structure = None
        boundary = None

        body_structure_match = BODY_STRUCTRUE.search(metadata)
        if body_structure_match:
            body_structure = body_structure_match.group(1)

            boundary_matches = BOUNDARY_EXTRACTOR.search(body_structure)
            if boundary_matches:
                boundary = boundary_matches.group(1)
            first_structure = extract_first_bodystructure(body_structure.lower())

            if first_structure:
                charset_match = CHARSET_EXTRACTOR.search(first_structure)
                if charset_match:
                    self.charset = charset_match.group(1)

                encoding_match = ENCODING_EXTRACTOR.search(first_structure)
                if not encoding_match:
                    encoding_match = ENCODING_EXTRACTOR.search(body_structure.lower())
                self.encoding = encoding_match.group(0) if encoding_match else "8bit"

        if boundary:
            body = extract_first_subsection(body, boundary)

        if self.encoding == "quoted-printable":
            body_decoded = decodestring(body)
        elif self.encoding == "base64":
            try:
                body_decoded = b64decode(body)
            except TypeError:
                body_decoded = ""
        else:
            body_decoded = body

        try:
            self.body = unicode(body_decoded, self.charset, errors='replace')
        except LookupError as error:
            self.body = error
        except UnicodeDecodeError as error:
            self.body = error

    def full_message(self, callback=None):
        """Fetches the full version of the message that this message is a teaser
        version of."""

        def _on_full_msg_fetched(full_msg):
            return _cmd(callback, full_msg)

        return _cmd_cb(self.mailbox.fetch, _on_full_msg_fetched, bool(callback), self.uid, full=True)


class Message(MessageBase):
    """Message objects represent individual emails in a Gmail inbox.

    Clients should not need to create instances of this class directly, but
    should rely on instances of the pygmail.account.Account class (and the
    related objects returned from the mailbox() methods) to load and provide
    pygmail.message.Message instances as needed.

    Instances have zero or more of the following properties:
        id      -- an identifier of this email
        uid     -- the unique identifier for this email in its mailbox
        flags   -- a list of zero or more flags (ex \Seen)
        date    -- the date (as a string) of when this message was sent
        sender  -- the email account this email was sent from
        subject -- the subject, if any, of the email

    """

    def __init__(self, mailbox, metadata, headers, body):
        """Initilizer for pygmai.message.Message objects

        Args:
            message  -- The tupple describing basic information about the
                        message.  The first index should contain metadata
                        informattion (eg message's uid), and the second
                        index contains header information (date, subject, etc.)
            mailbox  -- Reference to a pygmail.mailbox.Mailbox object that
                        represents the mailbox this message exists in

        """
        super(Message, self).__init__(mailbox, metadata, headers, METADATA_PATTERN)

        self.has_built_body_strings = None
        self.encoding = None
        self.body_html = None
        self.body_plain = None
        self.encoding_error = None

        self.raw = email.message_from_string(body)
        self.charset = self.raw.get_content_charset()

    def set_header(self, key, value, current_encoding='ascii'):
        """Sets a header, stored as utf-8 unicode

        Args:
            key   -- the header value desired
            value -- the value to encode and set in the current message

        Keyword Args:
            current_encoding -- The current encoding of the given value
        """
        unicode_value = unicode(value, current_encoding, errors='replace')
        self.headers[key] = eh.Header(unicode_value, 'utf-8')

    def _build_body_strings(self):
        if not self.has_built_body_strings:

            self.body_plain = u''
            self.body_html = u''

            for part in typed_subpart_iterator(self.raw, 'text', 'plain'):
                section_encoding = message_part_charset(part, self.raw) or self.charset
                section_text = utf8_encode_message_part(part, self.raw,
                                                        section_encoding)
                if is_encoding_error(section_text):
                    self.encoding_error = section_text
                else:
                    self.body_plain += section_text

            for part in typed_subpart_iterator(self.raw, 'text', 'html'):
                section_encoding = message_part_charset(part, self.raw) or self.charset
                section_text = utf8_encode_message_part(part, self.raw,
                                                        section_encoding)
                if is_encoding_error(section_text):
                    self.encoding_error = section_text
                else:
                    self.body_html += section_text

            self.has_built_body_strings = True

    def html_body(self):
        """Returns the HTML version of the message body, if available

        Lazy loads the HTML body of the email message from the server and
        returns the HTML version of the body, if one was provided

        Returns:
            The HTML version of the email body, or None if the message has no
            body (or the body is only in plain text)

        """
        self._build_body_strings()
        if self.encoding_error:
            return self.encoding_error
        else:
            return self.body_html or None

    def plain_body(self):
        """Returns the plain text version of the message body, if available

        Lazy loads the plain text version of the email body from the IMAP
        server, if it hasn't already been brought down

        Returns:
            The plain text version of the email body, or None if the message
            has no body (or the body is only provided in HTML)

        """
        self._build_body_strings()
        if self.encoding_error:
            return self.encoding_error
        else:
            return self.body_plain or None

    def attachments(self, callback=None):
        """Returns a list of attachment portions of the current message.

        Returns:
            A list of zero or more pygmail.message.Attachment objects
        """
        # First try returning a cached version of all the attachments
        # associated with this message.  If one doesn't exist, we need to fetch
        # and build the associated attribute objects

        try:
            return _cmd(callback, self._attachments)
        except AttributeError:
            is_attachment = lambda x: x['Content-Disposition'] and "attachment" in x['Content-Disposition']
            self._attachments = [Attachment(s, self) for s in self.raw.walk() if is_attachment(s)]
            return _cmd(callback, self._attachments)

    def as_string(self):
        """Returns a representation of the message as a raw string

        Lazy loads the raw text version of the email message, if it hasn't
        already been fetched.

        Returns:
            The full, raw text of the email message, or None if there was
            an error fetching it

        """
        return self.raw.as_string()

    def save(self, trash_folder, safe_label=None, header_label="PyGmail", callback=None):
        """Copies changes to the current message to the server

        Since we can't write to or update a message directly in IMAP, this
        method simulates the same effect by deleting the current message, and
        then writing a new message into IMAP that matches the current state
        of the the current message object.

        Args:
            trash_folder -- the name of the folder / label that is, in the
                            current account, the trash container

        Keyword Args:
            safe_label   -- If not None, a copy of this message will be saved into
                            a label with the given name. This version is nearly
                            identical to the current message, but has a unique
                            message id and seralized state in the header. This
                            copy serves as a transactional record. Once the
                            message is successfully saved, this copy will be
                            deleted.
            header_label -- The label to use when writing serialized state into
                            the header of this message. If safe_label is None,
                            this argument will have no effect.

        Returns:
            True on success, and in all other instances an error object
        """
        @pygmail.errors.check_imap_response(callback)
        def _on_post_labeling(imap_response):
            return _cmd(callback, True)

        @pygmail.errors.check_imap_state(callback)
        def _on_post_append_connection(connection):
            # Since the X-GM-LABELS are formmated in a very non ovious way
            # using ATOM, STRING, and ASTRING formatting, each with different
            # types of escaping, we don't bother trying to parse it, at least
            # for the time being.  We just send the raw value sent to use
            # from gmail back at them.
            #
            # This has the substantial downside though that there is no
            # nice / easy way to add / remove labels from pygmail messages,
            # at least currently
            #
            # @todo parse and rewrite labels correctly
            labels_value = '(%s)' % (self.labels_raw or '',)
            return _cmd_cb(connection.uid, _on_post_labeling, bool(callback),
                           "STORE", self.uid, "+X-GM-LABELS", labels_value)

        @pygmail.errors.check_imap_response(callback)
        def _on_append(imap_response):
            data = extract_data(imap_response)
            self.uid = data[0].split()[2][:-1]
            return _cmd_cb(self.conn, _on_post_append_connection, bool(callback))

        @pygmail.errors.check_imap_state(callback)
        def _on_received_connection(connection):
            flags_string = '(%s)' % (' '.join(self.flags),) if self.flags else "()"
            return _cmd_cb(connection.append, _on_append, bool(callback),
                           self.mailbox.name, flags_string,
                           self.internal_date or time.gmtime(),
                           self.raw.as_string())

        @pygmail.errors.check_imap_response(callback)
        def _on_select(is_selected):
            return _cmd_cb(self.conn, _on_received_connection, bool(callback))

        @pygmail.errors.check_imap_response(callback)
        def _on_delete(was_deleted):
            return _cmd_cb(self.mailbox.select, _on_select, bool(callback))

        # If we're not using the safe / transactional method of creating
        # a copy before we delete the existing version, we can just skip
        # ahead to the delete action. Otherwise, we need to first create
        # a safe version of this message.
        return _cmd_cb(self.delete, _on_delete, bool(callback), trash_folder)

    def remove_attachment(self, attachment):
        """Removes a given attachment from the message body. This method
        alters the message representation in place, not on the server, so
        to commit this change the caller should then call save() on the
        message object.

        Args:
            attachment -- a pygmail.message.Attachment object, representing
                          an attachment in the body of the current email message

        Return:
            True if an attachment was removed, otherwise False
        """
        # The strategy here is to walk through all parts of the message
        # and see if we can find a part of the message that matches
        # that encapuslated in the attachment. If so, we can then rewrite
        # the payload of the parent element in the email message to contain
        # whatever it contained before minus the message attachment section
        # (if the parent is multipart) or an empty string (if the parent is
        # is not multipart)
        def _find_in_tree(node, parent=None):
            if node.is_multipart():
                parts = node.get_payload()
                for part in parts:
                    rs = _find_in_tree(part, node)
                    if rs:
                        return rs
            else:
                if node.as_string() == attachment.raw.as_string():
                    return node, parent

        is_in_message = _find_in_tree(self.raw)
        if not is_in_message:
            return False

        attach_msg, parent_msg = is_in_message
        if parent_msg:
            parent_parts = parent_msg.get_payload()
            parent_parts.remove(attach_msg)
            parent_msg.set_payload(parent_parts)
        else:
            attach_msg.set_payload("")
        return True

    def replace(self, find, replace, trash_folder, callback=None):
        """Performs a body-wide string search and replace

        Note that this search-and-replace is pretty dumb, and will fail
        in, for example, HTML messages where HTML tags would alter the search
        string.

        Args:
            find         -- the search term to look for as a string, or a tuple
                            of items to replace with corresponding items in the
                            replace tuple
            replace      -- the string to replace instances of the "find" term
                            with, or a tuple of terms to replace the
                            corresponding strings in the find tuple
            trash_folder -- the name of the folder / label that is, in the
                            current account, the trash container

        Returns:
            True on success, and in all other instances an error object
        """
        def _set_content_transfer_encoding(part, encoding):
            try:
                del part['Content-Transfer-Encoding']
            except:
                ""
            part.add_header('Content-Transfer-Encoding', encoding)

        valid_content_types = ('plain', 'html')

        for valid_type in valid_content_types:

            for part in typed_subpart_iterator(self.raw, 'text', valid_type):

                section_encoding = part['Content-Transfer-Encoding']

                # If the message section doesn't advertise an encoding,
                # then default to quoted printable. Otherwise the module
                # will default to base64, which can cause problems
                if not section_encoding:
                    section_encoding = "quoted-printable"
                else:
                    section_encoding = section_encoding.lower()

                section_charset = message_part_charset(part, self.raw)
                new_payload_section = utf8_encode_message_part(
                    part, self.raw, section_charset)

                if is_encoding_error(new_payload_section):
                    self.encoding_error = new_payload_section
                    return _cmd(callback, self.encoding_error)

                if isinstance(find, tuple) or isinstance(find, list):
                    for i in range(0, len(find)):
                        new_payload_section = new_payload_section.replace(
                            find[i], replace[i])
                else:
                    new_payload_section = new_payload_section.replace(
                        find, replace)

                new_payload_section = new_payload_section.encode(
                    part._orig_charset, errors="replace")

                if section_encoding == "quoted-printable":
                    new_payload_section = encodestring(new_payload_section,
                                                       quotetabs=0)
                    part.set_payload(new_payload_section, part._orig_charset)
                    _set_content_transfer_encoding(part, "quoted-printable")
                elif section_encoding == "base64":
                    part.set_payload(new_payload_section, part._orig_charset)
                    ENC.encode_base64(part)
                    _set_content_transfer_encoding(part, "base64")
                elif section_encoding in ('7bit', '8bit'):
                    part.set_payload(new_payload_section, part._orig_charset)
                    ENC.encode_7or8bit(part)
                    _set_content_transfer_encoding(part, section_encoding)
                elif section_encoding == "binary":
                    part.set_payload(new_payload_section, part._orig_charset)
                    part['Content-Transfer-Encoding'] = 'binary'
                    _set_content_transfer_encoding(part, 'binary')

                del part._normalized
                del part._orig_charset

        def _on_save(was_success):
            return _cmd(callback, was_success)

        return _cmd_cb(self.save, _on_save, bool(callback), trash_folder)

    def save_copy(self, safe_label, header_label="PyGmail", callback=None):
        """Saves a semi-identical copy of the message in another label / mailbox
        in the gmail account. The saved message is intented
        to be different enough that it can safely live in the gmail account
        alongside the current version of the message.

        Args:
            safe_label -- If not None, a copy of this message will be saved into
                          a label with the given name. This version is nearly
                          identical to the current message, but has a unique
                          message id and seralized state in the header. This
                          copy serves as a transactional record. Once the
                          message is successfully saved, this copy will be
                          deleted.

        Keyword Args:
            header_label -- The label to use when writing serialized state into
                            the header of this message

        Returns:
            The tuple two identifiers of the newly created message, the uid and
            the header's message-id if a new message was successfully created,
            and False in all other situations.
        """

        @pygmail.errors.check_imap_response(callback)
        def _on_post_safe_labeling(imap_response, message_uid, message_id):
            response = (message_uid, message_id) if message_uid else False
            return _cmd(callback, response)

        @pygmail.errors.check_imap_state(callback)
        def _post_safe_save_connection(connection, message_uid, message_id):
            cbp = dict(message_uid=message_uid, message_id=message_id)
            label_value = '(%s)' % (safe_label,)
            return _cmd_cb(connection.uid, _on_post_safe_labeling,
                           bool(callback), "STORE", message_uid, "X-GM-LABELS",
                           label_value, callback_args=cbp)

        @pygmail.errors.check_imap_response(callback)
        def _on_safe_save_append(imap_response, message_copy):
            data = extract_data(imap_response)
            msg_uid = data[0].split()[2][:-1]
            cbp = dict(message_uid=msg_uid, message_id=message_copy['Message-Id'])
            return _cmd_cb(self.conn, _post_safe_save_connection, bool(callback),
                           callback_args=cbp)

        @pygmail.errors.check_imap_state(callback)
        def _on_safe_save_connection(connection, message_copy):
            cbp = dict(message_copy=message_copy)
            return _cmd_cb(connection.append, _on_safe_save_append,
                           bool(callback),  self.mailbox.name, '(\Seen)',
                           self.internal_date or time.gmtime(),
                           message_copy.as_string(),
                           callback_args=cbp)

        @pygmail.errors.check_imap_response(callback)
        def _on_safe_save_message(message_copy):
            cbp = dict(message_copy=message_copy)
            return _cmd_cb(self.conn, _on_safe_save_connection, bool(callback),
                           callback_args=cbp)

        return _cmd_cb(self.safe_save_message, _on_safe_save_message, bool(callback))

    def safe_save_message(self, header_label="PyGmail", callback=None):
        """Create a text version of the message that is similar to, but not
        identical to, the current message. The text version of this is intented
        to be different enough that it can safely live in the gmail account
        alongside the current version of the message.

        Keyword Args:
            header_label -- The label to use when writing serialized state into
                            the header of this message

        Returns:
            A message object, which is a near copy of the current message,
            but with a new message id and with the flags and labels serilized
            into a header.
        """
        from base64 import b64encode
        try:
            import cPickle as pickle
        except:
            import pickle

        copied_message = email.message_from_string(self.raw.as_string())

        stripped_headers = []
        # First seralize the state we'll loose when we write this copy
        # of the message to a safe, second location

        for header_to_copy in ('In-Reply-To', 'References', 'Sender'):
            try:
                header_value = copied_message[header_to_copy]
                del copied_message[header_to_copy]
                stripped_headers.append((header_to_copy, header_value))
            except:
                pass

        serialized_data = dict(message_id=self.message_id, flags=self.flags,
                               labels=self.labels_raw, headers=stripped_headers,
                               subject=copied_message['Subject'])

        serilization = pickle.dumps(serialized_data)
        custom_header = "X-%s-Data" % (header_label,)
        copied_message[custom_header] = b64encode(serilization)

        h = sha256()
        h.update(copied_message[custom_header])

        # Next generate a new unique ID we can use for identifying this
        # message. The only requirement here is to be unique in the account
        # and to be formatted correctly.
        new_message_id = "<%s@pygmail>" % (h.hexdigest(),)

        try:
            copied_message.replace_header("Message-Id", new_message_id)
        except:
            copied_message.add_header("Message-Id", new_message_id)
        new_subject = " ** %s - Backup ** " % (copied_message['Subject'],)
        try:
            copied_message.replace_header('Subject', new_subject)
        except KeyError:
            copied_message.add_header('Subject', new_subject)
        return _cmd(callback, copied_message)


class Attachment(object):
    """A class to represent the attachments to a given email message.  Instances
    of this class are not intended to be instantiated directly, but managed from
    instances of pygmail.message.Message objects."""

    def __init__(self, msg_part, message):
        """Initializer for Attachment object

        Args:
            msg_part -- A email.Message object representing the attachment part
                        of the email message
            message --  The pygmail.message.Message instance that represents
                        the email message that contains this attachment
        """
        self.raw = msg_part
        self.type = msg_part.get_content_type()
        self.name_raw = msg_part.get_filename()
        self.message = message

    def __eq__(self, other):
        """Two messages are only considered equal if they are both instances
        of pygmail.message.Attachment and the text they're representing is
        equal"""
        if not isinstance(other, Attachment):
            return False
        return self.raw.to_string() == other.raw.to_string()

    def name(self):
        """Returns the original filename for the attachment, if available.
        This method handles decoding any internationalized encoding of header
        values

        Return:
            The name of the file attachment, if available
        """
        try:
            return self._name
        except AttributeError:
            # Check to see if the filename is something other than ascii
            if len(self.name_raw) > 4 and self.name_raw[:2] == "=?" and self.name_raw[-2:] == "?=":
                file_name = eh.decode_header(self.name_raw)[0]
                if len(file_name) == 2:
                    self._name = unicode(file_name[0], file_name[1],
                                         errors='replace')
            else:
                self._name = self.name_raw
            return self._name

    def sha256(self):
        """Returns a hash of the base64 decoded version of the contents of this
        message.  Since we're hashing w/o having to decode the attachment file,
        this is slightly faster than hashing the result of Attachment.body

        Return:
            A SHA256 hash (as a hex byte string) of the base64 version of the
            attachment
        """
        try:
            return self._hash
        except AttributeError:
            h = sha256()
            h.update(self.raw.get_payload())
            self._hash = h.hexdigest()
            return self._hash

    def remove(self):
        """Removes the attachment from the body of the containing message.

        Return:
            True if the current attachment was removed from the parent (ie
            if any changes were made) and False in all other cases)
        """
        return self.message.remove_attachment(self)

    def body(self):
        """Returns a decoded, byte string version of the content of the
        attachment, which usually results in just base64 decoding the contents
        of the message.  This base64 decoded value is locally cached
        so that subsequent requests are free

        Return:
            The byte string version of the attachment
        """
        try:
            return self._body
        except AttributeError:
            self._body = self.raw.get_payload(decode=True)
            return self._body
