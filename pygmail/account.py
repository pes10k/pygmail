import imaplib2
import mailbox
import patching
from pygmail.utilities import loop_cb_args, add_loop_cb, extract_data, extract_type
from pygmail.errors import register_callback_if_error, is_auth_error, AuthError, check_for_response_error, is_imap_error, IMAPError


__version__ = '0.3'


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

    def __init__(self, email, oauth2_token=None, id_params=None, imap_class=None):
        """Creates an Account instances

        Args:
            email -- The email address of the account being connected to

        Keyword args:
            oauth2_token   -- An OAuth2 access token for use when connecting
                              with the given email address (default: None)
            id_params      -- A dict of keyword parameters used to id the current
                              connection to google. If provided, each connection
                              and authentication will be followed by an
                              identificaiton
            imap_class     -- Class responsible for handling IMAP traffic with
                              Gmail.  Most of the time it'll make sense to leave
                              this as None (which will use the default
                              imaplib2.IMAP4_SSL class), but this option can
                              be used to shim in other, API compatible classes.
        """
        if not imap_class:
            imap_class = imaplib2.IMAP4_SSL

        self.email = email
        self.conn = imap_class(Account.HOST)
        self.oauth2_token = oauth2_token
        self.connected = False
        self.id_params = id_params

        # A reference to the last selected / stated mailbox in the current
        # account.  This reference is kept so that we don't have to do
        # redundant calls to the IMAP server re-selecting the current mailbox.
        self.last_viewed_mailbox = None

        # A lazy-loaded collection of mailbox objects representing
        # the mailboxes in the current account.
        self.boxes = None

    def add_mailbox(self, name, callback=None):
        """Creates a new mailbox / folder in the current account. This is
        implemented using the gmail X-GM-LABELS IMAP extension.

        Args:
            name -- the name of the folder to create in the gmail account.

        Return:
            True if a new folder / label was created. Otherwise, False (such
            as if the folder already exists)
        """

        def _on_mailbox_creation(imap_response):
            error = check_for_response_error(imap_response)
            if error:
                loop_cb_args(callback, error)
            else:
                response_type = extract_type(imap_response)
                if response_type == "NO":
                    loop_cb_args(callback, False)
                else:
                    data = extract_data(imap_response)
                    self.boxes = None
                    was_success = data[0] == "Success"
                    loop_cb_args(callback, was_success)

        def _on_connection(connection):
            if is_auth_error(connection):
                loop_cb_args(callback, connection)
            else:
                connection.create(name,
                                  callback=add_loop_cb(_on_mailbox_creation))

        self.connection(callback=add_loop_cb(_on_connection))

    def mailboxes(self, include_meta=False, callback=None):
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
                if is_auth_error(connection) or is_imap_error(connection):
                    loop_cb_args(callback, connection)
                else:
                    connection.list(callback=add_loop_cb(_on_mailboxes))

            self.connection(callback=add_loop_cb(_on_connection))

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
            if is_auth_error(mailboxes) or is_imap_error(mailboxes):
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
            not accepted by the Gmail server, and otherwise an imaplib2
            connection object.

        """
        def _on_authentication(imap_response):
            response, cb_arg, error = imap_response
            if not response or response[0] != "OK":
                error = "User / OAuth2 token (%s, %s) were not accepted" % (
                    self.email, self.oauth2_token)
                loop_cb_args(callback, AuthError(error))
            else:
                self.connected = True
                if self.id_params:
                    self.id(callback=callback)
                else:
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
                    callback=add_loop_cb(_on_authentication)
                )
            except:
                loop_cb_args(callback, AuthError(""))

    def clear_mailbox_cache(self):
        """Clears the local cache of mailboxes names / objects. This will
        force the Account object to refetch the list of mailboxes
        from the GMail IMAP server the next time a mailbox is fetched.

        Returns:
            The number of objects were cleared out of the cache
        """
        num_mailboxes = len(self.boxes)
        self.boxes = None
        return num_mailboxes

    def close(self, callback=None):
        """Closes the IMAP connection to GMail

        Closes and logs out of the IMAP connection to GMail.

        Returns:
            True if a connection was closed, and False if this close request
            was a NOOP
        """
        def _on_logout(imap_response):
            if not register_callback_if_error(imap_response, callback, require_ok=False):
                typ = extract_type(imap_response)
                self.connected = False
                loop_cb_args(callback, typ == "BYE")

        def _on_close(imap_response):
            if not register_callback_if_error(imap_response, callback):
                self.conn.logout(callback=add_loop_cb(_on_logout))

        if self.last_viewed_mailbox:
            try:
                self.conn.close(callback=add_loop_cb(_on_close))
            except Exception as e:
                loop_cb_args(callback, IMAPError(e))
        else:
            _on_close(None)

    def id(self, callback=None):
        """Sends the ID command to the Gmail server, as requested / suggested
        by [Google](https://developers.google.com/google-apps/gmail/imap_extensions)

        The order that the terms will be sent in undefined, but each key
        will come immediatly before its value.

        Args:
            params -- A dictionary of terms that should be sent to google.

        Returns:
            The imaplib2 connection object on success, and an error object
            otherwise
        """
        def _on_id(imap_response):
            if not register_callback_if_error(imap_response, callback):
                loop_cb_args(callback, self.conn)

        def _on_connection(connection):
            id_params = []
            for k, v in self.id_params.items():
                id_params.append('"' + k + '"')
                id_params.append('"' + v + '"')
            id_string = "(" + " ".join(id_params) + ")"
            connection.id(id_string, callback=add_loop_cb(_on_id))

        self.connection(callback=add_loop_cb(_on_connection))
