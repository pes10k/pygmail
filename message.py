import email
import re
import base64
import time
import email.utils
from email.parser import HeaderParser


class GmailMessage(object):
    """ GmailMessage objects represent individual emails in a Gmail inbox.

    Clients should not need to create instances of this class directly, but
    should rely on instances of the GmailAccount class (and the related objects
    returned from the mailbox() methods) to load and provide GmailMessage
    instances as needed.

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

    # Single, class-wide reference to an email header parser
    HEADER_PARSER = HeaderParser()

    def __init__(self, message, mailbox):
        """ Initilizer for GmailMessage objectrs

        Args:
            message  -- The tupple describing basic information about the
                        message.  The first index should contain metadata
                        informattion (eg message's uid), and the second
                        index contains header information (date, subject, etc.)
            mailbox  -- Reference to a GmailMailbox object that represents the
                        mailbox this message exists in

        """
        self.mailbox = mailbox
        self.account = mailbox.account
        self.connection = self.account.connection()

        self.id, self.uid, flags = GmailMessage.METADATA_PATTERN.match(message[0]).groups()
        self.flags = flags.split()

        ### First parse out the metadata about the email message
        headers = GmailMessage.HEADER_PARSER.parsestr(message[1])
        self.date = headers["Date"]
        self.sender = headers["From"]
        self.subject = None if "Subject" not in headers else headers["Subject"]
        self.has_fetched_body = False
        self.raw = None
        self.sent_datetime = None

    def fetch_body(self):
        """ Returns the body of the email

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
            status, data = self.connection.uid(
                "FETCH",
                self.uid,
                "(RFC822)"
            )
            if status != "OK":
                return None
            self.raw = email.message_from_string(data[0][1])

        self.body_plain = ''
        self.body_html = ''

        for part in self.raw.walk():
            content_type = str(part.get_content_type())
            if content_type == 'text/plain':
                self.body_plain += part.get_payload(decode=True)
            elif content_type == 'text/html':
                self.body_html += part.get_payload(decode=True)

        self.has_fetched_body = True
        return self.body_plain if self.body_html == "" else self.body_html

    def html_body(self):
        """ Returns the HTML version of the message body, if available

        Lazy loads the HTML body of the email message from the server and
        returns the HTML version of the body, if one was provided

        Returns:
            The HTML version of the email body, or None if the message has no
            body (or the body is only in plain text)

        """
        self.fetch_body()
        return None if self.body_html == "" else self.body_html

    def plain_body(self):
        """ Returns the plain text version of the message body, if available

        Lazy loads the plain text version of the email body from the IMAP
        server, if it hasn't already been brought down

        Returns:
            The plain text version of the email body, or None if the message
            has no body (or the body is only provided in HTML)

        """
        self.fetch_body()
        return None if self.body_plain == "" else self.body_plain

    def raw_message(self):
        """ Returns a representation of the message as a raw string

        Lazy loads the raw text version of the email message, if it hasn't
        already been fetched.

        Returns:
            The full, raw text of the email message, or None if there was
            an error fetching it

        """
        self.fetch_body()
        return None if self.raw is None else self.raw.as_string()

    def is_read(self):
        """ Checks to see if the message has been flaged as read

        Returns:
            True if the message is flagged as read, and otherwise False

        """
        return "\Seen" in self.flags

    def datetime(self):
        """ Returns the date of when the message was sent

        Lazy-loads the date of when the message was sent (as a datetime object)
        based on the string date/time advertised in the email header

        Returns:
            A datetime object representation of when the message was sent

        """
        if self.sent_datetime is None:
            self.sent_datetime = email.utils.parsedate(self.date)
        return self.sent_datetime

    def delete(self):
        """ Deletes the message from the IMAP server

        Returns:
            A reference to the current object

        """
        connection = self.connection
        self.mailbox.select()

        # First move the message we're trying to delete to the gmail
        # trash.
        connection.uid('COPY', self.uid, "[Gmail]/Trash")

        # Then delete the message from the current mailbox
        connection.uid('STORE', self.uid, '+FLAGS', '(\Deleted)')
        connection.expunge()

        # Then, find the message we just added to the trash and mark that
        # to be deleted as well.
        #
        # @note there is a possible race condition here, since if someone else
        # sends us a message between when we did the above and below, we'll
        # end up deleting the wrong message
        connection.select("[Gmail]/Trash")
        delete_uid = connection.uid('SEARCH', None, 'All')[1][0].split()[-1]
        rs, data = connection.uid('STORE', delete_uid, '+FLAGS', '\\Deleted')
        connection.expunge()

        # Last, reselect the current mailbox.  We do this directly, instead
        # of through the mailbox.select() method, since we didn't hand the
        # token off to the "Trash" mailbox above.
        self.connection.select(self.mailbox.name)
        return self

    def save(self):
        """ Copies changes to the current message to the server

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

        rs, data = self.connection.append(
            self.mailbox.name,
            " ".join(["(%s)" % flag for flag in self.flags]),
            self.datetime(),
            self.raw_message()
        )
        return self

    def replace(self, find, replace):
        """ Performs a body-wide string search and replace

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
        """ Replaces text in the body of the message with a RegEx

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
