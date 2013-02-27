import email
import re
import email.utils
from quopri import encodestring
import email.encoders as ENC
from email.parser import HeaderParser
from email.Iterators import typed_subpart_iterator
import email.header as eh
from pygmail.address import Address
import account as GA


def message_part_charset(part, message):
    """Get the charset of the a part of the message"""
    part_charset = part.get_content_charset() or part.get_charset()
    if part_charset:
        return part_charset

    message_charset = message.get_content_charset() or message.get_charset()
    return message_charset or "ascii"


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
        The payload of the email portion, encoded as UTF-8, or a
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


def is_encoding_error(msg):
    return msg.__class__ is UnicodeDecodeError or msg.__class__ is LookupError


class Message(object):
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

    # A regular expression used for extracting metadata information out
    # of the raw IMAP returned string.
    METADATA_PATTERN = re.compile(r'(\d*) \(X-GM-MSGID (\d*) X-GM-LABELS \((.*)\) UID (\d*) FLAGS \((.*)\)\s')

    # A similar regular expression used for extracting metadata when the
    # message doesn't contain any flags
    METADATA_PATTERN_NOFLAGS = re.compile(r'(\d*) \(X-GM-MSGID (\d*) X-GM-LABELS \((.*)\) UID (\d*)\s')

    # Single, class-wide reference to an email header parser
    HEADER_PARSER = HeaderParser()

    def __init__(self, message, mailbox, full_body=False, flags=None):
        """Initilizer for pgmail.message.Message objects

        Args:
            message  -- The tupple describing basic information about the
                        message.  The first index should contain metadata
                        informattion (eg message's uid), and the second
                        index contains header information (date, subject, etc.)
            mailbox  -- Reference to a pygmail.mailbox.Mailbox object that
                        represents the mailbox this message exists in

        """
        self.mailbox = mailbox
        self.account = mailbox.account
        self.conn = self.account.connection
        metadata_rs = Message.METADATA_PATTERN.match(message[0])

        # If we're loading from a full RFC822 asked for message, the flags
        # come not in the header string, but at the end of the message
        if not metadata_rs:
            metadata_short_rs = Message.METADATA_PATTERN_NOFLAGS.match(message[0])
            self.id, self.gmail_id, self.labels, self.uid = metadata_short_rs.groups()
        else:
            self.id, self.gmail_id, self.labels, self.uid, self.flags = metadata_rs.groups()

        self.flags = self.flags.split() if self.flags else []
        self.labels = self.labels.split() if self.labels else []

        # Prune the quoted quote hell scape
        self.flags = [flag.replace(r'\\\\', r'\\') for flag in self.flags]
        self.labels = [label.replace(r'\\\\', r'\\') for label in self.labels]

        ### First parse out the metadata about the email message
        headers = Message.HEADER_PARSER.parsestr(message[1])
        self.headers = headers

        self.date = headers["Date"]
        self.sender = headers["From"]
        self.to = headers["To"]
        self.cc = headers["Cc"] if "Cc" in headers else ()

        if "Subject" not in headers:
            self.subject = None
        else:
            raw_subject = headers["Subject"]
            subject_parts = eh.decode_header(raw_subject)[0]
            if subject_parts[1] is not None:
                self.subject = unicode(subject_parts[0], subject_parts[1], errors='replace')
            else:
                self.subject = unicode(subject_parts[0], 'ascii', errors='replace')

        self.message_id = headers['Message-Id']

        if full_body:
            self.raw = email.message_from_string(message[1])
            self.charset = self.raw.get_content_charset()
        else:
            self.raw = None

        self.has_built_body_strings = None
        self.sent_datetime = None
        self.encoding = None
        self.body_html = None
        self.body_plain = None
        self.encoding_error = None

    def __eq__(self, other):
        """ Overrides equality operator to check by uid and mailbox name """
        return (isinstance(other, Message) and
            self.uid == other.uid and
            self.mailbox.name == other.mailbox.name)

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

    def _build_body_strings(self):
        if not self.has_built_body_strings:
            self.body_plain = u''
            self.body_html = u''

            for part in typed_subpart_iterator(self.raw, 'text', 'plain'):
                section_encoding = message_part_charset(part, self.raw) or self.charset
                section_text = utf8_encode_message_part(part, self.raw, section_encoding)
                if is_encoding_error(section_text):
                    self.encoding_error = section_text
                else:
                    self.body_plain += section_text

            for part in typed_subpart_iterator(self.raw, 'text', 'html'):
                section_encoding = message_part_charset(part, self.raw) or self.charset
                section_text = utf8_encode_message_part(part, self.raw, section_encoding)
                if is_encoding_error(section_text):
                    self.encoding_error = section_text
                else:
                    self.body_html += section_text

            self.has_built_body_strings = True

    def fetch_raw_body(self, callback=None):
        """Returns the body of the email

        Fetches the body / main part of this email message.  Note that this
        doesn't currently fetch attachents (which are ignored)

        Returns:
            If there is both an HTML and plain text version of this message,
            the HTML body is returned.  If neither is available, or an
            error occurs fetching the body of the messages, None is returned

        """
        def _on_fetch((response, cb_arg, error)):
            typ, data = response
            if typ != "OK":
                GA.loop_cb_args(callback, None)
            else:
                self.raw = email.message_from_string(data[0][1])
                self.charset = self.raw.get_content_charset()
                GA.loop_cb_args(callback, self.raw)

        def _on_connection(connection):
            connection.uid("FETCH", self.uid, "(RFC822)",
                callback=GA.add_loop_cb(_on_fetch))

        def _on_select(result):
            self.conn(callback=GA.add_loop_cb(_on_connection))

        # First check to see if we've already pulled down the body of this
        # message, in which case we can just return it w/o having to
        # pull from the server again
        if self.raw:
            GA.loop_cb_args(callback, self.raw)
        else:
            # Next, also check to see if we at least have a reference to the
            # raw, underlying email message object, in which case we can save
            # another network call to the IMAP server
            self.mailbox.select(callback=GA.add_loop_cb(_on_select))

    def html_body(self, callback=None):
        """Returns the HTML version of the message body, if available

        Lazy loads the HTML body of the email message from the server and
        returns the HTML version of the body, if one was provided

        Returns:
            The HTML version of the email body, or None if the message has no
            body (or the body is only in plain text)

        """
        if callback:
            def _on_fetch_raw_body(full_body):
                self._build_body_strings()
                if self.encoding_error:
                    GA.loop_cb_args(callback, self.encoding_error)
                else:
                    GA.loop_cb_args(callback, self.body_html or None)

            self.fetch_raw_body(callback=GA.add_loop_cb(_on_fetch_raw_body))
        else:
            self._build_body_strings()
            if self.encoding_error:
                return self.encoding_error
            else:
                return self.body_html or None

    def plain_body(self, callback=None):
        """Returns the plain text version of the message body, if available

        Lazy loads the plain text version of the email body from the IMAP
        server, if it hasn't already been brought down

        Returns:
            The plain text version of the email body, or None if the message
            has no body (or the body is only provided in HTML)

        """
        if callback:
            def _on_fetch_raw_body(full_body):
                self._build_body_strings()
                if self.encoding_error:
                    GA.loop_cb_args(callback, self.encoding_error)
                else:
                    GA.loop_cb_args(callback, self.body_plain or None)

            self.fetch_raw_body(callback=GA.add_loop_cb(_on_fetch_raw_body))
        else:
            self._build_body_strings()
            if self.encoding_error:
                return self.encoding_error
            else:
                return self.body_plain or None

    def as_string(self, callback=None):
        """Returns a representation of the message as a raw string

        Lazy loads the raw text version of the email message, if it hasn't
        already been fetched.

        Returns:
            The full, raw text of the email message, or None if there was
            an error fetching it

        """
        def _on_fetch_raw_body(raw):
            GA.loop_cb_args(callback, raw.as_string() if raw else None)

        self.fetch_raw_body(callback=GA.add_loop_cb(_on_fetch_raw_body))

    def is_read(self):
        """Checks to see if the message has been flaged as read

        Returns:
            True if the message is flagged as read, and otherwise False

        """
        return "\Seen" in self.flags

    def datetime(self):
        """Returns the date of when the message was sent

        Lazy-loads the date of when the message was sent (as a datetime object)
        based on the string date/time advertised in the email header

        Returns:
            A tuple object representation of when the message was sent

        """
        if self.sent_datetime is None:
            self.sent_datetime = email.utils.parsedate(self.date)
        return self.sent_datetime

    def delete(self, callback=None):
        """Deletes the message from the IMAP server

        Returns:
            A reference to the current object

        """
        if not callback:
            self.mailbox.select()

            # First move the message we're trying to delete to the gmail
            # trash.
            self.conn().uid('COPY', self.uid, "[Gmail]/Trash")

            # Then delete the message from the current mailbox
            self.conn().uid('STORE', self.uid, '+FLAGS', '(\Deleted)')
            self.conn().expunge()

            self.conn().select("[Gmail]/Trash")
            deleted_uid = self.conn().uid('SEARCH',
                '(HEADER MESSAGE-ID "' + self.message_id + '")')[0].split()[-1]
            rs, data = self.conn().uid('STORE', deleted_uid, '+FLAGS',
                '\\Deleted')
            self.conn().expunge()

            # Last, reselect the current mailbox.  We do this directly, instead
            # of through the mailbox.select() method, since we didn't hand the
            # token off to the "Trash" mailbox above.
            self.conn().select(self.mailbox.name)
            return self
        else:
            def _on_recevieved_connection_6(connection):
                connection.select(self.mailbox.name,
                    callback=GA.add_loop_cb(callback))

            def _on_expunge_complete((response, cb_arg, error)):
                self.conn(callback=GA.add_loop_cb(_on_recevieved_connection_6))

            def _on_recevieved_connection_5(connection):
                connection.expunge(callback=GA.add_loop_cb(_on_expunge_complete))

            def _on_delete_complete((response, cb_arg, error)):
                self.conn(callback=GA.add_loop_cb(_on_recevieved_connection_5))

            def _on_received_connection_4(connection, deleted_uid):
                connection.uid('STORE', deleted_uid, '+FLAGS',
                    '\\Deleted', callback=GA.add_loop_cb(_on_delete_complete))

            def _on_search_for_message_complete(rs):
                response, cb_arg, error = rs
                typ, data = response
                if typ != "OK" or not data:
                    print response
                deleted_uid = data[0].split()[-1]
                self.conn(callback=lambda conn: GA.io_loop().add_callback(lambda: _on_received_connection_4(conn, deleted_uid)))

            def _on_received_connection_3(connection):
                connection.uid('SEARCH',
                    '(HEADER Message-ID "' + self.message_id + '")',
                    callback=GA.add_loop_cb(_on_search_for_message_complete))

            def _on_trash_selected((response, cb_arg, error)):
                self.conn(callback=GA.add_loop_cb(_on_received_connection_3))

            def _on_received_connection_2(connection):
                connection.select("[Gmail]/Trash",
                    callback=GA.add_loop_cb(_on_trash_selected))

            def _on_message_moved((response, cb_arg, error)):
                self.conn(callback=GA.add_loop_cb(_on_received_connection_2))

            def _on_received_connection(connection):
                connection.uid('COPY', self.uid, "[Gmail]/Trash",
                    callback=GA.add_loop_cb(_on_message_moved))

            def _on_mailbox_select(msg_count):
                self.conn(callback=GA.add_loop_cb(_on_received_connection))

            self.mailbox.select(callback=GA.add_loop_cb(_on_mailbox_select))

    def save(self, callback=None):
        """Copies changes to the current message to the server

        Since we can't write to or update a message directly in IMAP, this
        method simulates the same effect by deleting the current message, and
        then writing a new message into IMAP that matches the current state
        of the the current message object.

        Returns:
            A reference to the current object

        """
        def _on_post_labeling(rs):
            GA.loop_cb_args(callback, rs)

        def _on_post_search_select(connection):
            labels_value = '(%s)' % ' '.join(self.labels) if self.labels else "()"
            connection.uid("STORE", self.uid,
                "+X-GM-LABELS", labels_value,
                callback=GA.add_loop_cb(_on_post_labeling)
            )

        def _on_message_id_search((response, cb_arg, error)):
            typ, data = response
            self.uid = data[0].split()[-1]
            self.conn(callback=GA.add_loop_cb(_on_post_search_select))

        def _on_post_append_select(connection):
            connection.uid('SEARCH',
                '(HEADER Message-ID "' + self.message_id + '")',
                callback=GA.add_loop_cb(_on_message_id_search))

        def _on_append((response, cb_arg, error)):
            # Add error handling here!
            if len(self.labels) == 0:
                # If there were no labels attached to this message, we
                # don't have to futz with it any more, we can just
                # go ahead and return back to the main process
                GA.loop_cb(callback)
            else:
                # Otherwise, we need to search down the new UID of the
                # message we just added, so that we can stick the
                # labels to it
                self.conn(callback=GA.add_loop_cb(_on_post_append_select))

        def _on_received_connection(connection, raw_string):
            connection.append(
                self.mailbox.name,
                '(%s)' % ' '.join(self.flags) if self.flags else "()",
                self.datetime(),
                raw_string,
                callback=GA.add_loop_cb(_on_append)
            )

        def _on_select(msg_count, raw_string):
            callback_params = dict(raw_string=raw_string)
            self.conn(callback=GA.add_loop_cb_args(
                _on_received_connection, callback_params)
            )

        def _on_delete(rs, raw_string):
            callback_params = dict(raw_string=raw_string)
            self.mailbox.select(callback=GA.add_loop_cb_args(
                _on_select, callback_params)
            )

        def _on_as_string(raw_string):
            callback_params = dict(raw_string=raw_string)
            self.delete(callback=GA.add_loop_cb_args(_on_delete, callback_params))

        self.as_string(callback=GA.add_loop_cb(_on_as_string))

    def replace(self, find, replace, callback=None):
        """Performs a body-wide string search and replace

        Note that this search-and-replace is pretty dumb, and will fail
        in, for example, HTML messages where HTML tags would alter the search
        string.

        Args:
            find    -- the search term to look for as a string, or a tuple of
                       items to replace with corresponding items in the
                       replace tuple
            replace -- the string to replace instances of the "find" term with,
                       or a tuple of terms to replace the corresponding strings
                       in the find tuple
        Returns:
            A reference to the current message object

        """
        def _on_fetch_raw_body(raw):
            valid_content_types = ('plain', 'html')

            for valid_type in valid_content_types:

                for part in typed_subpart_iterator(self.raw, 'text', valid_type):

                    section_encoding = part['Content-Transfer-Encoding']

                    # If the message section doesn't advertise an encoding,
                    # then default to quoted printable.  Otherwise the module
                    # will default to base64, which can cause problems
                    if not section_encoding:
                        part.add_header('Content-Transfer-Encoding', "quoted-printable")
                        section_encoding = "quoted-printable"

                    section_charset = message_part_charset(part, self.raw)
                    new_payload_section = utf8_encode_message_part(part, self.raw, section_charset)

                    if isinstance(find, tuple) or isinstance(find, list):
                        for i in range(0, len(find)):
                            new_payload_section = new_payload_section.replace(find[i], replace[i])
                    else:
                        new_payload_section = new_payload_section.replace(find, replace)

                    new_payload_section = new_payload_section.encode(part._orig_charset, errors="replace")

                    if section_encoding == "quoted-printable":
                        new_payload_section = encodestring(new_payload_section, quotetabs=0)
                        part.set_payload(new_payload_section, part._orig_charset)
                    elif section_encoding == "base64":
                        part.set_payload(new_payload_section, part._orig_charset)
                        ENC.encode_base64(part)
                    elif section_encoding in ('7bit', '8bit'):
                        part.set_payload(new_payload_section, part._orig_charset)
                        ENC.encode_7or8bit(part)

                    del part._normalized
                    del part._orig_charset

            self.save(callback=callback)

        self.fetch_raw_body(callback=GA.add_loop_cb(_on_fetch_raw_body))
