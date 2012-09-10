import imaplib
import mailbox


class GmailAccount(object):
    """Represents a connection with a Google Mail account

    Instances of this class each wrap a connection to a gmail account,
    connected over IMAP_SSL.  This connection can either be established
    using a user / pass combination or xoauth.  If an xoauth string IMAP_SSL
    provided at initilization, xoauth will be used for the connection.
    Otherwise, a standard user/pass will be used.

    """

    HOST = "imap.googlemail.com"

    def __init__(self, email, xoauth_string=None, password=None):
        """ Creates a GmailAccount Instances

        Keyword arguments:
            xoauth_string -- The xoauth connection string for connecting with
                             the account (default: None)
            password      -- The password to use when establishing
                             the connection

        Args:
            email -- The email address of the account being connected to

        """
        self.email = email
        self.conn = imaplib.IMAP4_SSL(GmailAccount.HOST)
        self.xoauth_string = xoauth_string
        self.password = password
        self.connected = False
        self.last_viewed_mailbox = None

    def mailboxes(self):
        """ Returns a list of all mailboxes in the current account

        Returns:
            A list of GmailMailbox objects, each representing one mailbox
            in the IMAP account

        """
        response_code, boxes_raw = self.connection().list()
        mailboxes = []
        for box in boxes_raw:
            if "[" not in box:
                mailboxes.append(mailbox.GmailMailbox(self, box))
        return mailboxes

    def connection(self):
        """ Creates an authenticated connection to gmail over IMAP

        Attempts to authenticate a connection with the gmail server using
        xoauth if a connection string has been provided, and otherwise using
        the provided password.

        If a connection has already successfully been created, no action will
        be taken (so multiplie calls to this method will result in a single
        connection effort, once a connection has been successfully created).

        Returns:
            True if the connection was successfully authenticated, and
            otherwise False
        Raises:
            GmailAuthError, if the given connection parameters are not accepted
            by the Gmail server

        """
        if not self.connected:
            if self.password:
                rs = self.conn.login(self.email, self.password)
                if rs[0] != "OK":
                    error = "User / Pass (%s, %s) were not accepted : %s" % (
                        self.email,
                        self.password,
                        rs[0]
                    )
                    raise GmailAuthError(error)
            else:
                rs = self.conn.authenticate(
                    "XOAUTH",
                    lambda x: self.xoauth_string
                )
                if rs[0] != "OK":
                    error = "User / XOAUTH (%s, %s) were not accepted" % (
                        self.email,
                        self.xoauth_string
                    )
                    raise GmailAuthError(error)
        self.connected = True
        return self.conn


class GmailAuthError(Exception):
    """ An exeption signifying that an authentication attempt with the gmail
    server was not accepted."""
