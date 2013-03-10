import re
import string
import message as GM
from pygmail.utilities import loop_cb_args, add_loop_cb, extract_data, add_loop_cb_args
from pygmail.errors import register_callback_if_error, is_auth_error


def parse_fetch_request(response, size=2):
    length = len(response)
    if length % size != 0 or response[0] is None:
        if __debug__:
            print response
        raise Exception("Invalid chunk size requested, %d sized chunks from %d sized list" % (size, length))
    else:
        i = 0
        while i < length:
            item = []
            j = 0
            while j < size:
                item.append(response[length - 1 - i - j])
                j += 1
            i += size
            yield item


def page_from_list(a_list, limit, offset):
    """ Retreives the paginated section from the provided list

    Helps pagination needs by extracting only the section of the given list
    described by the limit and offset parameters w/o causing invalid index
    errors.

    Args:
        a_list -- A list of any length
        limit  -- The maximum number of elements to return from the list.
                  If False, no items will be truncated
        offset -- The index of the first element in the list to return

    Return:
        A slice from the given list with at most "limit" elements, or all
        elements after offset if limit is False

    """
    count = len(a_list)
    # If the given offset is greater than the total number
    # of messages in the inbox, there are no messages to return
    if count <= offset:
        return []
    else:
        first_elm_index = offset

    if limit is False:
        return a_list[first_elm_index:]
    else:
        last_req_item = offset + limit
        last_elm_index = count if last_req_item >= count else last_req_item
        return a_list[first_elm_index:last_elm_index]


class Mailbox(object):
    """Represents a single mailbox within a gmail account

    Instances of this class are not intended to be initilized directly, but
    instead managed by a pygmail.account.Account instances

    """

    # Classwide regular expression used to extract the human readable versions
    # of the mailbox names from the full, IMAP versions
    NAME_PATTERN = re.compile(r'\((.*?)\) "(.*)" (.*)')

    # Classwide, simple regular expression to only digits in a string
    COUNT_PATTERN = re.compile(r'[^0-9]')

    def __init__(self, account, full_name):
        """ Initilizes a mailbox object

        Args:
            account      -- An initilized pygmail.account.Account object, which
                            represents the gmail account this mailbox exists in
            mailbox_name -- The full name of the mailbox, in IMAP format, not
                            in easy, human readable format

        """
        self.account = account
        self.conn = account.connection
        self.full_name = full_name
        self.name = Mailbox.NAME_PATTERN.match(full_name).groups()[2]

    def __str__(self):
        return "<Mailbox: %s>" % (self.name,)

    def count(self, callback=None):
        """Returns a count of the number of emails in the mailbox

        Returns:
            The int value of the number of emails in the mailbox, or None on
            error

        """
        def _on_select_complete(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                self.account.last_viewed_mailbox = self
                loop_cb_args(callback,
                             int(Mailbox.COUNT_PATTERN.sub("", str(data))))

        def _on_connection(connection):
            connection.select(mailbox=self.name,
                              callback=add_loop_cb(_on_select_complete))

        self.account.connection(callback=add_loop_cb(_on_connection))

    def delete_message(self, uid, message_id, callback=None):
        """Allows for deleting a message by UID, without needing to pulldown
        and populate a Message object first.

        Args:
            uid        -- the uid for a message in the current mailbox
            message_id -- the message id, from the email headers of the message
                          to delete

        Returns:
            A boolean description of whether a message was successfully deleted
        """
        def _on_original_mailbox_reselected(imap_response):
            if not register_callback_if_error(imap_response, callback):
                loop_cb_args(callback, True)

        def _on_recevieved_connection_7(connection):
            connection.select(self.name,
                              callback=add_loop_cb(_on_original_mailbox_reselected))

        def _on_expunge_complete(imap_response):
            if not register_callback_if_error(imap_response, callback):
                self.conn(callback=add_loop_cb(_on_recevieved_connection_7))

        def _on_recevieved_connection_6(connection):
            connection.expunge(callback=add_loop_cb(_on_expunge_complete))

        def _on_delete_complete(imap_response):
            if not register_callback_if_error(imap_response, callback):
                self.conn(callback=add_loop_cb(_on_recevieved_connection_6))

        def _on_received_connection_4(connection, deleted_uid):
            connection.uid('STORE', deleted_uid, 'FLAGS', '\\Deleted',
                           callback=add_loop_cb(_on_delete_complete))

        def _on_search_for_message_complete(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                deleted_uid = data[0].split()[-1]
                callback_params = dict(deleted_uid=deleted_uid)
                self.conn(callback=add_loop_cb_args(_on_received_connection_4,
                                                    callback_params))

        def _on_received_connection_3(connection):
            connection.uid('SEARCH',
                           '(HEADER Message-ID "' + message_id + '")',
                           callback=add_loop_cb(_on_search_for_message_complete))

        def _on_trash_selected(imap_response):
            if not register_callback_if_error(imap_response, callback):
                self.conn(callback=add_loop_cb(_on_received_connection_3))

        def _on_received_connection_2(connection):
            connection.select("[Gmail]/Trash",
                              callback=add_loop_cb(_on_trash_selected))

        def _on_message_moved(imap_response):
            if not register_callback_if_error(imap_response, callback):
                self.conn(callback=add_loop_cb(_on_received_connection_2))

        def _on_connection(connection):
            connection.uid('COPY', uid, "[Gmail]/Trash",
                           callback=add_loop_cb(_on_message_moved))

        def _on_select(was_selected):
            if not register_callback_if_error(was_selected, callback):
                self.account.connection(callback=_on_connection)

        self.select(callback=add_loop_cb(_on_select))

    def delete(self, callback=None):
        """Removes the mailbox / folder from the current gmail account. In
        Gmail's implementation, this translates into deleting a Gmail label.

        Return:
            True if a folder / label was removed. Otherwise, False (such
            as if the current folder / label doesn't exist at deletion)
        """
        def _on_mailbox_deletion(imap_response):
            if not register_callback_if_error(imap_response, callback, require_ok=False):
                data = extract_data(imap_response)
                was_success = data[0] == "Success"
                loop_cb_args(callback, was_success)

        def _on_connection(connection):
            if is_auth_error(connection):
                loop_cb_args(callback, connection)
            else:
                connection.delete(self.name,
                                  callback=add_loop_cb(_on_mailbox_deletion))

        self.account.connection(callback=add_loop_cb(_on_connection))

    def select(self, callback=None):
        """Sets this mailbox as the current active one on the IMAP connection

        In order to make sure we don't make many many redundant calls to the
        IMAP server, we allow the account managing object to keep track
        of which mailbox was last set as active.  If the current mailbox is
        active, this method does nothing.

        Returns:
            True if any changes were made, otherwise False

        """
        def _on_count_complete(num):
            self.account.last_viewed_mailbox = self
            loop_cb_args(callback, True)

        if self is self.account.last_viewed_mailbox:
            loop_cb_args(callback, False)
        else:
            self.count(callback=add_loop_cb(_on_count_complete))

    def search(self, term, limit=100, offset=0, only_uids=False, callback=None):
        """Searches for messages in the inbox that contain a given phrase

        Seaches for a given phrase in the current mailbox, and returns a list
        of messages that have the phrase in the HTML and/or plain text part
        of their body.

        Note that this search is done on the server, and not against the
        message text directly, so its not a string level search (it falls
        through to Google's more intellegent search)

        Args:
            term -- the search term to search for in the current mailbox

        Keyword arguments:
            limit     -- The maximum number of messages to return
            offset    -- The first message to return out of the entire set of
                         messages in the inbox
            only_uids -- If True, only the UIDs of the matching messages will
                         be returned, instead of full message headers.

        Returns:
            A list of messages or uids (depending on the call arguments) in case
            of success, and an IMAPError object in all other cases.
        """
        def _on_search(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                ids = string.split(data[0])
                ids_to_fetch = page_from_list(ids, limit, offset)
                self.messages_by_id(ids_to_fetch, only_uids=only_uids,
                                    callback=add_loop_cb(callback))

        def _on_connection(connection):
            rs, data = connection.search(None, 'X-GM-RAW', term,
                                         callback=add_loop_cb(_on_search))

        def _on_mailbox_selected(was_changed):
            self.account.connection(callback=add_loop_cb(_on_connection))

        self.select(callback=add_loop_cb(_on_mailbox_selected))

    def messages(self, limit=100, offset=0, only_uids=False, callback=None):
        """Returns a list of all the messages in the inbox

        Fetches a list of all messages in the inbox.  This list is by default
        limited to only the first 100 results, though pagination can trivially
        be implemented using the limit / offset parameters

        Keyword arguments:
            limit     -- The maximum number of messages to return.  If None,
                         everything will be returned
            offset    -- The first message to return out of the entire set of
                         messages in the inbox
            only_uids -- If True, only the UIDs of the matching messages will
                         be returned, instead of full message headers.

        Return:

            A two index tupple.  The element in the first index is a
            list of zero or more pygmail.message.Message objects (or uids if
            only_uids is TRUE), or None if no information could be found about
            the mailbox. The second element is the total number of messages (not
            just those returned from the limit-offset parameters)

        """
        def _on_messages_by_id(messages):
            loop_cb_args(callback, messages)

        def _on_search(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                ids = string.split(data[0])
                ids_to_fetch = page_from_list(ids, limit, offset)
                self.messages_by_id(ids_to_fetch, only_uids=only_uids,
                                    callback=add_loop_cb(_on_messages_by_id))

        def _on_connection(connection):
            connection.search(None, 'ALL', callback=add_loop_cb(_on_search))

        def _on_select_complete(result):
            self.account.connection(callback=add_loop_cb(_on_connection))

        self.select(callback=add_loop_cb(_on_select_complete))

    def fetch_all(self, uids, callback=None, include_body=False):
        """Returns a list of messages, each specified by their UID

        Returns zero or more GmailMessage objects, each representing a email
        message in the current mailbox.

        Arguments:
            uids -- A list of zero or more email uids

        Returns:
            Zero or more pygmail.message.Message objects, representing any
            messages that matched a provided uid
        """
        def _on_fetch(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                messages = []
                if len(data) > 1:
                    for msg_parts in parse_fetch_request(data):
                        flags, body = msg_parts
                        messages.append(GM.Message(body, self,
                                                   full_body=include_body,
                                                   flags=flags))
                loop_cb_args(callback, messages)

        def _on_connection(connection):
            if include_body:
                request = '(X-GM-MSGID FLAGS X-GM-LABELS BODY.PEEK[])'
            else:
                request = '(X-GM-MSGID UID FLAGS X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'
            connection.uid("FETCH", ",".join(uids), request,
                           callback=add_loop_cb(_on_fetch))

        def _on_select(result):
            self.account.connection(callback=add_loop_cb(_on_connection))

        if uids:
            self.select(callback=add_loop_cb(_on_select))
        else:
            loop_cb_args(callback, None)

    def fetch(self, uid, callback=None, include_body=False):
        """Returns a single message from the mailbox by UID

        Returns a single message object, representing the message in the current
        mailbox with the specific UID

        Arguments:
            uid -- the numeric, unique identifier of the message in the mailbox

        Returns:
            A pygmail.message.Message object representing the email message, or
            None if none could be found.  If an error is encountered, an
            IMAPError object will be returned.
        """

        def _on_fetch(imap_response):
            if not register_callback_if_error(imap_response, callback):
                data = extract_data(imap_response)
                for msg_parts in parse_fetch_request(data):
                    flags, body = msg_parts
                    loop_cb_args(callback,
                                 GM.Message(body, self,
                                            full_body=include_body,
                                            flags=flags))

        def _on_connection(connection):
            if include_body:
                request = '(X-GM-MSGID FLAGS X-GM-LABELS BODY.PEEK[])'
            else:
                request = '(X-GM-MSGID UID FLAGS X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'

            connection.uid("FETCH", uid, request,
                           callback=add_loop_cb(_on_fetch))

        def _on_select(result):
            self.account.connection(callback=add_loop_cb(_on_connection))

        self.select(callback=add_loop_cb(_on_select))

    def messages_by_id(self, ids, only_uids=False, callback=None):
        """Fetches messages in the mailbox by their id

        Returns a list of all messages in the current mailbox that match
        any of the provided ids.

        Args:
            ids       -- A list of zero or more email ids, which should match
                         messages in the current mailbox
            only_uids -- If True, only the UIDs for the given volitile message
                         ids will be returned, instead of the entire populated
                         GmailMessage object

        Returns:
            A list of zero or more message objects (or uids) if success, and
            an error object in all other situations
        """
        # If we were told to fetch no messages, fast "callback" and don't
        # bother doing any network io
        if len(ids) == 0:
            loop_cb_args(callback, [])
        else:
            def _on_fetch(imap_response):
                if not register_callback_if_error(imap_response, callback):
                    data = extract_data(imap_response)
                    if only_uids:
                        uids = [string.split(elm, " ")[4][:-1] for elm in data]
                        loop_cb_args(callback, uids)
                    else:
                        messages = []
                        for msg_parts in parse_fetch_request(data):
                            flags, body = msg_parts
                            messages.append(GM.Message(body, self, flags=flags))
                        loop_cb_args(callback, messages)

            def _on_connection(connection):
                if only_uids:
                    request = '(X-GM-MSGID UID)'
                else:
                    request = '(X-GM-MSGID UID FLAGS X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'
                connection.fetch(",".join(ids), request,
                                 callback=add_loop_cb(_on_fetch))

            def _on_select(result):
                self.account.connection(callback=add_loop_cb(_on_connection))

            self.select(callback=add_loop_cb(_on_select))
