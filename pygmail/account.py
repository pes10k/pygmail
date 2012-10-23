import imaplib
import mailbox
from string import split


class GmailAccount(object):
    """Represents a connection with a Google Mail account

    Instances of this class each wrap a connection to a gmail account,
    connected over IMAP_SSL.  This connection can either established in
    any of the three methods Google currently supports:
        - standard password
        - XOauth
        - OAuth2

    Note that the first two methods are currently depreciated by Google and will
    be removed in the future, so better to get on the OAuth2 train.

    """

    HOST = "imap.googlemail.com"

    def __init__(self, email, xoauth_string=None, password=None, oauth2_token=None):
        """Creates a GmailAccount Instances

        Keyword arguments:
            xoauth_string  -- The xoauth connection string for connecting with
                              the account using XOauth (default: None)
            password       -- The password to use when establishing
                              the connection when using the user/pass auth
                              method (default: None)
            oauth2_token   -- An OAuth2 access token for use when connecting
                              with the given email address (default: None)

        Arguments:
            email -- The email address of the account being connected to

        """
        self.email = email
        self.conn = imaplib.IMAP4_SSL(GmailAccount.HOST)
        self.xoauth_string = xoauth_string
        self.oauth2_token = oauth2_token
        self.password = password
        self.connected = False

        # A reference to the last selected / stated mailbox in the current
        # account.  This reference is kept so that we don't have to do
        # redundant calls to the IMAP server re-selecting the current mailbox.
        self.last_viewed_mailbox = None

        # A lazy-loaded collection of mailbox objects representing
        # the mailboxes in the current account.
        self.boxes = None

    def __del__(self):
        """Close the IMAP connection to GMail when the object is being destroyed"""
        if self.last_viewed_mailbox:
            self.close()

        if self.connected:
            self.conn.logout()

    def mailboxes(self):
        """Returns a list of all mailboxes in the current account

        Returns:
            A list of GmailMailbox objects, each representing one mailbox
            in the IMAP account

        """
        if self.boxes is None:
            response_code, boxes_raw = self.connection().list()
            self.boxes = []
            for box in boxes_raw:
                if "[" not in box:
                    self.boxes.append(mailbox.GmailMailbox(self, box))
        return self.boxes

    def get(self, mailbox_name):
        """Returns the mailbox with a given name in the current account

        Arguments:
            mailbox_name -- The name of a mailbox to look for in the current
                            account

        Returns:
            None if no mailbox matching the given name could be found.
            Otherwise, returns the GmailMailbox object representing the
            mailbox.

        """
        for mailbox in self.mailboxes():
            if mailbox.name == mailbox_name:
                return mailbox
        return None

    #def call(self, callback, max_attempts=2):
        """Makes a request to the IMAP server, and reconnects if needed

        Makes call against the imap connection (wrapped in the given callback
        lambda), but catches cases where the connection has died reconnects
        if needed to the IMAP server.

        Arguments:
            callback -- A lambda that wraps an authenticated request against
                        the IMAP connection

        Keyword arguments:
            max_attempts -- The maximum number of times to attempt to
                            re-establish the connection with the IMAP server

        Returns:
            The result of the request, on success
        """

    def connection(self):
        """Creates an authenticated connection to gmail over IMAP

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
            if self.oauth2_token:
                auth_params = self.email, self.oauth2_token
                xoauth2_string = 'user=%s\1auth=Bearer %s\1\1' % auth_params
                print xoauth2_string
                rs = self.conn.authenticate("XOAUTH2", lambda x: xoauth2_string)
                if rs[0] != "OK":
                    error = "User / OAuth2 token (%s, %s) were not accepted" % (
                        self.email, self.oauth2_token)
                    raise GmailAuthError(error)
            elif self.password:
                rs = self.conn.login(self.email, self.password)
                if rs[0] != "OK":
                    error = "User / Pass (%s, %s) were not accepted : %s" % (
                        self.email, self.password, rs[0])
                    raise GmailAuthError(error)
            else:
                rs = self.conn.authenticate(
                    "XOAUTH",
                    lambda x: self.xoauth_string
                )
                if rs[0] != "OK":
                    error = "User / XOAUTH (%s, %s) were not accepted" % (
                        self.email, self.xoauth_string)
                    raise GmailAuthError(error)
        self.connected = True
        return self.conn

    def close(self):
        """Closes the IMAP connection to GMail

        Closes and logs out of the IMAP connection to GMail.

        Returns:
            Reference to the current object
        """
        self.conn.close()

    def info(self):
        """Returns information about the GMail IMAP server

        Returns information about the GMail IMAP server, including capabilities
        and protocol information.

        Return:
            A list of each capability advertised but the IMAP server, or
            None if an error occured
        """
        rs, data = self.connection().capability()
        return None if rs != "OK" else split(data[0], " ")


class GmailAuthError(Exception):
    """An exeption signifying that an authentication attempt with the gmail
    server was not accepted."""
