import imaplib2
import mailbox
from pygmail.utilities import loop_cb_args, add_loop_cb, extract_data
from pygmail.errors import register_callback_if_error, is_auth_error, AuthError


class Account(object):
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

    def __init__(self, email, oauth2_token=None):
        """Creates an Account instances

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
        self.conn = imaplib2.IMAP4_SSL(Account.HOST)
        self.oauth2_token = oauth2_token
        self.connected = False

        # A reference to the last selected / stated mailbox in the current
        # account.  This reference is kept so that we don't have to do
        # redundant calls to the IMAP server re-selecting the current mailbox.
        self.last_viewed_mailbox = None

        # A lazy-loaded collection of mailbox objects representing
        # the mailboxes in the current account.
        self.boxes = None

    def __del__(self):
        """Close the IMAP connection when the object is being destroyed"""
        if hasattr(self, 'conn') and hasattr(self, 'connected'):
            self.conn.logout()

    def mailboxes(self, callback=None, include_meta=False):
        """Returns a list of all mailboxes in the current account

        Keyword Args:
            callback     -- optional callback function, which will cause the
                            conection to operate in an async mode
            include_meta -- Whether or not the Gmail special meta mailboxes
                            (such as "All Messages", "Drafts", etc.) should be
                            included

        Returns:
            A list of pygmail.mailbox.Mailbox objects, each representing one
            mailbox in the IMAP account

        """
        if self.boxes is not None:
            loop_cb_args(callback, self.boxes)
        else:
            def _on_mailboxes(imap_response):
                if not register_callback_if_error(imap_response, callback):
                    data = extract_data(imap_response)
                    self.boxes = []
                    for box in data:
                        if include_meta or "[" not in box:
                            self.boxes.append(mailbox.Mailbox(self, box))
                    loop_cb_args(callback, self.boxes)

            def _on_connection(connection):
                if is_auth_error(connection):
                    loop_cb_args(callback, connection)
                else:
                    connection.list(callback=lambda rs: loop_cb_args(_on_mailboxes, rs))

            self.connection(callback=lambda conn: loop_cb_args(_on_connection, conn))

    def get(self, mailbox_name, callback=None, include_meta=False):
        """Returns the mailbox with a given name in the current account

        Args:
            mailbox_name -- The name of a mailbox to look for in the current
                            account
            include_meta -- Whether or not the Gmail special meta mailboxes
                            (such as "All Messages", "Drafts", etc.) should be
                            included

        Keyword Args:
            callback -- optional callback function, which will cause the
                        conection to operate in an async mode

        Returns:
            None if no mailbox matching the given name could be found.
            Otherwise, returns the pygmail.mailbox.Mailbox object representing
            the mailbox.

        """
        def _retreived_mailboxes(mailboxes):
            if is_auth_error(mailboxes):
                loop_cb_args(callback, mailboxes)
            else:
                for mailbox in mailboxes:
                    if mailbox.name == mailbox_name:
                        loop_cb_args(callback, mailbox)
                        return
                loop_cb_args(callback, None)

        self.mailboxes(callback=add_loop_cb(_retreived_mailboxes),
                       include_meta=include_meta)

    def connection(self, callback=None):
        """Creates an authenticated connection to gmail over IMAP

        Attempts to authenticate a connection with the gmail server using
        xoauth if a connection string has been provided, and otherwise using
        the provided password.

        If a connection has already successfully been created, no action will
        be taken (so multiplie calls to this method will result in a single
        connection effort, once a connection has been successfully created).

        Returns:
            pygmail.account.AuthError, if the given connection parameters are
            not accepted by the Gmail server

        """
        def _on_authentication((response, cb_arg, error)):
            if not response or response[0] != "OK":
                error = "User / OAuth2 token (%s, %s) were not accepted" % (
                    self.email, self.oauth2_token)
                loop_cb_args(callback, AuthError(error))
            else:
                self.connected = True
                loop_cb_args(callback, self.conn)

        if self.connected:
            loop_cb_args(callback, self.conn)
        else:
            auth_params = self.email, self.oauth2_token
            xoauth2_string = 'user=%s\1auth=Bearer %s\1\1' % auth_params
            try:
                self.conn.authenticate(
                    "XOAUTH2",
                    lambda x: xoauth2_string,
                    callback=lambda rs: loop_cb_args(_on_authentication, rs)
                )
            except:
                loop_cb_args(callback, AuthError(""))

    def close(self):
        """Closes the IMAP connection to GMail

        Closes and logs out of the IMAP connection to GMail.

        Returns:
            Reference to the current object
        """
        if self.last_viewed_mailbox:
            self.conn.close()
        self.conn.logout()
        self.connected = False
