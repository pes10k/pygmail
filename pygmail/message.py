import email
import re
import base64
import email.utils
from email.parser import HeaderParser
import email.header as eh
import sys


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


def encode_message_part(message_part, message_encoding):
    """Returns the payload of a part of an email, encoded as UTF-8

    Normalizes the text / contents of an email message to be UTF-8, regardless
    of its original encoding

    Arguments:
        message_part     -- a section of an email message
        message_encoding -- the advertised encoding of the entire message
                            that this message part was a part of

    Returns:
        The payload of the email portion, encoded as UTF-8
    """
    payload = message_part.get_payload(decode=True)
    if isinstance(payload, unicode):
        return payload
    else:
        encoding = message_encoding if not message_part.get_content_charset() else message_part.get_content_charset()
        if encoding and "utf-8" not in encoding:
            return unicode(payload, encoding, errors='replace')
        else:
            return unicode(payload, "ascii", errors='replace')


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
    METADATA_PATTERN = re.compile(r'(\d*) \(UID (\d*) FLAGS \((.*)\)\s')

    # A similar regular expression used for extracting metadata when the
    # message doesn't contain any flags
    METADATA_PATTERN_NOFLAGS = re.compile(r'(\d*) \(UID (\d*)\s')

    # Single, class-wide reference to an email header parser
    HEADER_PARSER = HeaderParser()

    def __init__(self, message, mailbox):
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

        match_rs = Message.METADATA_PATTERN.match(message[0])

        if match_rs is None:
            match_short_rs = Message.METADATA_PATTERN_NOFLAGS.match(message[0])
            self.id, self.uid = match_short_rs.groups()
            self.flags = []
        else:
            self.id, self.uid, flags = match_rs.groups()
            self.flags = flags.split()

        ### First parse out the metadata about the email message
        headers = Message.HEADER_PARSER.parsestr(message[1])
        self.date = headers["Date"]
        self.sender = headers["From"]
        if "Subject" not in headers:
            self.subject = None
        else:
            raw_subject = headers["Subject"]
            subject_parts = eh.decode_header(raw_subject)[0]
            if subject_parts[1] is not None:
                self.subject = unicode(subject_parts[0], subject_parts[1], errors='replace')
            else:
                self.subject = unicode(subject_parts[0], 'ascii', errors='replace')
        self.has_fetched_body = False
        self.raw = None
        self.sent_datetime = None
        self.encoding = None

    def __eq__(self, other):
        """ Overrides equality operator to check by uid and mailbox name """
        return (isinstance(other, Message) and
            self.uid == other.uid and
            self.mailbox.name == other.mailbox.name)

    def fetch_body(self):
        """Returns the body of the email

        Fetches the body / main part of this email message.  Note that this
        doesn't currently fetch attachents (which are ignored)

        Returns:
            If there is both an HTML and plain text version of this message,
            the HTML body is returned.  If neither is available, or an
            error occurs fetching the body of the messages, None is returned

        """
        # First check to see if we've already pulled down the body of this
        # message, in which case we can just return it w/o having to
        # pull from the server again
        if self.has_fetched_body:
            return self.body_plain if self.body_html == "" else self.body_html

        # Next, also check to see if we at least have a reference to the
        # raw, underlying email message object, in which case we can save
        # another network call to the IMAP server
        if self.raw is None:
            self.mailbox.select()
            status, data = self.conn().uid("FETCH", self.uid, "(RFC822)")
            if status != "OK":
                return None
            try:
                self.raw = email.message_from_string(data[0][1])
                self.charset = self.raw.get_content_charset()
            except:
                print "BAD MESSAGE"
                print "UID: " + self.uid
                print data
                sys.exit()

        self.body_plain = u''
        self.body_html = u''

        if self.raw is not None:
            for part in self.raw.walk():
                content_type = str(part.get_content_type())
                if content_type == 'text/plain':
                    self.body_plain += encode_message_part(part, self.charset)
                elif content_type == 'text/html':
                    self.body_html += encode_message_part(part, self.charset)

        self.has_fetched_body = True
        return self.body_plain if self.body_html == "" else self.body_html

    def html_body(self):
        """Returns the HTML version of the message body, if available

        Lazy loads the HTML body of the email message from the server and
        returns the HTML version of the body, if one was provided

        Returns:
            The HTML version of the email body, or None if the message has no
            body (or the body is only in plain text)

        """
        self.fetch_body()
        return None if self.body_html == "" else self.body_html

    def plain_body(self):
        """Returns the plain text version of the message body, if available

        Lazy loads the plain text version of the email body from the IMAP
        server, if it hasn't already been brought down

        Returns:
            The plain text version of the email body, or None if the message
            has no body (or the body is only provided in HTML)

        """
        self.fetch_body()
        return None if self.body_plain == "" else self.body_plain

    def raw_message(self):
        """Returns a representation of the message as a raw string

        Lazy loads the raw text version of the email message, if it hasn't
        already been fetched.

        Returns:
            The full, raw text of the email message, or None if there was
            an error fetching it

        """
        self.fetch_body()
        return None if self.raw is None else self.raw.as_string()

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
            A datetime object representation of when the message was sent

        """
        if self.sent_datetime is None:
            self.sent_datetime = email.utils.parsedate(self.date)
        return self.sent_datetime

    def delete(self):
        """Deletes the message from the IMAP server

        Returns:
            A reference to the current object

        """
        self.mailbox.select()

        # First move the message we're trying to delete to the gmail
        # trash.
        self.conn().uid('COPY', self.uid, "[Gmail]/Trash")

        # Then delete the message from the current mailbox
        self.conn().uid('STORE', self.uid, '+FLAGS', '(\Deleted)')
        self.conn().expunge()

        # Then, find the message we just added to the trash and mark that
        # to be deleted as well.
        #
        # @note there is a possible race condition here, since if someone else
        # sends us a message between when we did the above and below, we'll
        # end up deleting the wrong message
        self.conn().select("[Gmail]/Trash")
        delete_uid = self.conn().uid('SEARCH', None, 'All')[1][0].split()[-1]
        rs, data = self.conn().uid('STORE', delete_uid, '+FLAGS', '\\Deleted')
        self.conn().expunge()

        # Last, reselect the current mailbox.  We do this directly, instead
        # of through the mailbox.select() method, since we didn't hand the
        # token off to the "Trash" mailbox above.
        self.conn().select(self.mailbox.name)
        return self

    def save(self):
        """Copies changes to the current message to the server

        Since we can't write to or update a message directly in IMAP, this
        method simulates the same effect by deleting the current message, and
        then writing a new message into IMAP that matches the current state
        of the the current message object.

        Returns:
            A reference to the current object

        """
        self.fetch_body()
        self.delete()
        self.mailbox.select()

        rs, data = self.conn().append(
            self.mailbox.name,
            '(%s)' % ' '.join(self.flags),
            self.datetime(),
            self.raw_message()
        )
        return self

    def replace(self, find, replace):
        """Performs a body-wide string search and replace

        Note that this search-and-replace is pretty dumb, and will fail
        in, for example, HTML messages where HTML tags would alter the search
        string.

        Args:
            find    -- the search term to look for
            replace -- the string to replace instances of the "find" term with
        Returns:
            A reference to the current message object

        """
        self.fetch_body()
        encoding = self.raw.get("Content-Transfer-Encoding")

        for part in self.raw.walk():
            content_type = str(part.get_content_type())
            if content_type in ('text/plain', 'text/html'):
                section = part.get_payload(decode=True)
                new_payload = section.replace(find, replace)
                if encoding and encoding == "base64":
                    new_payload = base64.b64encode(new_payload)
                part.set_payload(new_payload)
        self.has_fetched_body = False
        return self

    def replace_re(self, regex, replace):
        """Replaces text in the body of the message with a RegEx

        Note that this search-and-replace is pretty dumb, and will fail
        in, for example, HTML messages where HTML tags would alter the search
        string.

        Args:
            regex   -- A compiled regular expression to find text in the body
                       of the current message
            replace -- A string to use to replace matches of the regular
                       expression
        Returns:
            A reference to the current message object

        """
        self.fetch_body()
        encoding = self.raw.get("Content-Transfer-Encoding")

        for part in self.raw.walk():
            content_type = str(part.get_content_type())
            if content_type in ('text/plain', 'text/html'):
                section = part.get_payload(decode=True)
                new_payload = regex.sub(replace, section)
                if encoding and encoding == "base64":
                    new_payload = base64.b64encode(new_payload)
                part.set_payload(new_payload)
        self.has_fetched_body = False
        return self
