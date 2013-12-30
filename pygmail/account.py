import imaplib2
import mailbox
import pygmail.errors
from pygmail.utilities import loop_cb_args, add_loop_cb, extract_data, extract_type, imap_cmd
from pygmail.errors import is_auth_error, AuthError, check_for_response_error, is_imap_error, IMAPError


__version__ = '0.6'


class Account(object):
    """Represents a connection with a Google Mail account

    Instances of this class each wrap a connection to a gmail account,
    connected over IMAP_SSL.  This connection can either established in
    any of the three methods Google currently supports:
        - standard password
        - OAuth2

    Note that the first two methods are currently depreciated by Google and will
    be removed in the future, so better to get on the OAuth2 train.

    """

    HOST = "imap.googlemail.com"

    def __init__(self, email, oauth2_token=None, password=None, id_params=None, imap_class=None):
        """Creates an Account instances

        Args:
            email -- The email address of the account being connected to

        Keyword args:
            oauth2_token   -- An OAuth2 access token for use when connecting
                              with the given email address (default: None)
            password       -- The password to use when connecting to the IMAP
                              account, if connecting with a standard user/pass
                              combo (ignored if an oauth2_token is provided)
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
        self.password = password
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

        @pygmail.errors.check_imap_state(callback)
        def _on_connection(connection):
            if is_auth_error(connection):
                loop_cb_args(callback, connection)
            else:
                # connection.create(name,
                #                   callback=add_loop_cb(_on_mailbox_creation))

                return imap_cmd(connection.create, _on_mailbox_creation,
                                func_args=[name], is_async=callback)

        # self.connection(callback=add_loop_cb(_on_connection))
        return imap_cmd(self.connection, _on_connection, is_async=callback)

    def all_mailbox(self, callback=None):
        """Returns a mailbox object that represents the [Gmail]/All Mail folder
        in the current account.  Note that this will reutrn the correct folder,
        regardless of the langauge of the current account

        Returns:
            A pygmail.mailbox.Mailbox instance representing the current,
            localized version of the [Gmail]/All Mail folder, or None
            if there was an error and one couldn't be found
        """
        @pygmail.errors.check_imap_response(callback)
        def _on_mailboxes(mailboxes):
            for box in mailboxes:
                if box.full_name.find('(\HasNoChildren \All)') == 0:
                    callback(box)
                    return
            callback(None)

        if self.boxes:
            _on_mailboxes(self.boxes)
        else:
            # self.mailboxes(callback=_on_mailboxes)
            return imap_cmd(self.mailboxes, _on_mailboxes, is_async=callback)

    def trash_mailbox(self, callback=None):
        """Returns a mailbox object that represents the [Gmail]/Trash folder
        in the current account.  Note that this will reutrn the correct folder,
        regardless of the langauge of the current account

        Returns:
            A pygmail.mailbox.Mailbox instance representing the current,
            localized version of the [Gmail]/Trash folder, or None
            if there was an error and one couldn't be found
        """
        @pygmail.errors.check_imap_response(callback)
        def _on_mailboxes(mailboxes):
            for box in mailboxes:
                if box.full_name.find('(\HasNoChildren \Trash)') == 0:
                    callback(box)
                    return
            callback(None)

        if self.boxes:
            _on_mailboxes(self.boxes)
        else:
            # self.mailboxes(callback=_on_mailboxes)
            return imap_cmd(self.mailboxes, _on_mailboxes, is_async=callback)


    def mailboxes(self, callback=None):
        """Returns a list of all mailboxes in the current account

        Keyword Args:
            callback     -- optional callback function, which will cause the
                            conection to operate in an async mode
        Returns:
            A list of pygmail.mailbox.Mailbox objects, each representing one
            mailbox in the IMAP account

        """
        if self.boxes is not None:
            loop_cb_args(callback, self.boxes)
        else:
            @pygmail.errors.check_imap_response(callback)
            def _on_mailboxes(imap_response):
                data = extract_data(imap_response)
                self.boxes = []
                for box in data:
                    self.boxes.append(mailbox.Mailbox(self, box))
                loop_cb_args(callback, self.boxes)

            @pygmail.errors.check_imap_state(callback)
            def _on_connection(connection):
                if is_auth_error(connection) or is_imap_error(connection):
                    loop_cb_args(callback, connection)
                else:
                    # connection.list(callback=add_loop_cb(_on_mailboxes))
                    return imap_cmd(connection.list, _on_mailboxes, is_async=callback)

            # self.connection(callback=add_loop_cb(_on_connection))
            return imap_cmd(self.connection, _on_connection, is_async=callback)


    def get(self, mailbox_name, callback=None):
        """Returns the mailbox with a given name in the current account

        Args:
            mailbox_name -- The name of a mailbox to look for in the current
                            account

        Keyword Args:
            callback -- optional callback function, which will cause the
                        conection to operate in an async mode

        Returns:
            None if no mailbox matching the given name could be found.
            Otherwise, returns the pygmail.mailbox.Mailbox object representing
            the mailbox.

        """
        @pygmail.errors.check_imap_response(callback)
        def _retreived_mailboxes(mailboxes):
            for mailbox in mailboxes:
                if mailbox.name == mailbox_name:
                    loop_cb_args(callback, mailbox)
                    return
            loop_cb_args(callback, None)

        # self.mailboxes(callback=add_loop_cb(_retreived_mailboxes))
        return imap_cmd(self.mailboxes, _retreived_mailboxes, is_async=callback)

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
            response, cb_arg, imap_error = imap_response
            if not response or response[0] != "OK":
                if self.oauth2_token:
                    error = "User / OAuth2 token (%s, %s) were not accepted" % (
                        self.email, self.oauth2_token)
                else:
                    error = "User / password (%s, %s) were not accepted" % (
                        self.email, self.password)
                if imap_error and len(imap_error) > 1:
                    error += " " + imap_error[1]
                loop_cb_args(callback, AuthError(error))
            else:
                self.connected = True
                if self.id_params:
                    # self.id(callback=callback)
                    return imap_cmd(self.id, callback, is_async=callback)
                else:
                    loop_cb_args(callback, self.conn)

        if self.connected:
            loop_cb_args(callback, self.conn)
        elif self.oauth2_token:
            auth_params = self.email, self.oauth2_token
            xoauth2_string = 'user=%s\1auth=Bearer %s\1\1' % auth_params
            try:
                # self.conn.authenticate(
                #     "XOAUTH2",
                #     lambda x: xoauth2_string,
                #     callback=add_loop_cb(_on_authentication)
                # )
                return imap_cmd(self.conn.authenticate,
                                _on_authentication,
                                "XOAUTH2", lambda x: xoauth2_string,
                                is_async=callback)
            except:
                loop_cb_args(callback, AuthError(""))
        else:
            try:
                # self.conn.login(self.email, self.password,
                #                 callback=add_loop_cb(_on_authentication))
                return imap_cmd(self.conn.login, _on_authentication,
                                self.email, self.password,
                                is_async=callback)
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
        @pygmail.errors.check_imap_response(callback, require_ok=False)
        def _on_logout(imap_response):
            typ = extract_type(imap_response)
            self.connected = False
            loop_cb_args(callback, typ == "BYE")

        @pygmail.errors.check_imap_response(callback, require_ok=False)
        def _on_close(imap_response):
            # self.conn.logout(callback=add_loop_cb(_on_logout))
            return imap_cmd(self.conn.logout, _on_logout, is_async=callback)

        if self.last_viewed_mailbox:
            try:
                # self.conn.close(callback=add_loop_cb(_on_close))
                return imap_cmd(self.conn.close, _on_close, is_async=callback)
            except Exception as e:
                loop_cb_args(callback, IMAPError(e))
        else:
            return _on_close(None)

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
        @pygmail.errors.check_imap_response(callback)
        def _on_id(imap_response):
            loop_cb_args(callback, self.conn)

        @pygmail.errors.check_imap_state(callback)
        def _on_connection(connection):
            id_params = []
            for k, v in self.id_params.items():
                id_params.append('"' + k + '"')
                id_params.append('"' + v + '"')
            # The IMAPlib2 exposed version of the "ID" command doesn't
            # format the parameters the same way gmail wants them, so
            # we just do it ourselves (imaplib2 wraps them in an extra
            # paren)

            # connection._simple_command('ID', "(" + " ".join(id_params) + ")",
            #                            callback=add_loop_cb(_on_id))
            imap_cmd(connection._simple_command, _on_id,
                     'ID', "(" + " ".join(id_params) + ")",
                     is_async=callback)

        # self.connection(callback=add_loop_cb(_on_connection))
        return imap_cmd(self.connection, _on_connection, is_async=callback)
