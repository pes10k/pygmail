import re
import string
import message as gm
import utilities as gu
import account as ga


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
        self.full_name = full_name
        self.name = Mailbox.NAME_PATTERN.match(full_name).groups()[2]

    def __str__(self):
        return self.name

    def count(self, callback=None):
        """Returns a count of the number of emails in the mailbox

        Returns:
            The int value of the number of emails in the mailbox, or None on
            error

        """
        if callback:
            def _on_select_complete((response, cb_arg, error)):
                typ, data = response
                if typ == "OK":
                    self.account.last_viewed_mailbox = self
                    ga.loop_cb_args(callback, Mailbox.COUNT_PATTERN.sub("", str(data)))
                else:
                    ga.loop_cb_args(callback, None)

            def _on_connection(connection):
                connection.select(mailbox=self.name, callback=ga.add_loop_cb(_on_select_complete))

            self.account.connection(callback=ga.add_loop_cb(_on_connection))
        else:
            connection = self.account.connection()
            typ, data = connection.select(mailbox=self.name)
            if typ != "OK":
                return None
            else:
                self.account.last_viewed_mailbox = self
                return Mailbox.COUNT_PATTERN.sub("", str(data))

    def select(self, callback=None):
        """Sets this mailbox as the current active one on the IMAP connection

        In order to make sure we don't make many many redundant calls to the
        IMAP server, we allow the account managing object to keep track
        of which mailbox was last set as active.  If the current mailbox is
        active, this method does nothing.

        Returns:
            True if any changes were made, otherwise False

        """
        if callback:
            def _on_count_complete(num):
                self.account.last_viewed_mailbox = self
                ga.loop_cb_args(callback, True)

            if self is self.account.last_viewed_mailbox:
                ga.loop_cb_args(callback, False)
            else:
                self.count(callback=ga.add_loop_cb(_on_count_complete))
        else:
            return self.count()

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
            A two index tupple.  The element in the first index is a
            list of zero or more pygmail.message.Message objects (or uids if
            only_uids is TRUE), or None if no information could be found about
            the mailbox.

        """
        def _on_search((response, cb_arg, error)):
            typ, data = response

            if typ != "OK":
                ga.loop_cb_args(callback, None)

            ids = string.split(data[0])
            ids_to_fetch = page_from_list(ids, limit, offset)
            self.messages_by_id(ids_to_fetch, only_uids=only_uids,
                callback=ga.add_loop_cb(callback))

        def _on_connection(connection):
            quoted = gu.quote(term)
            search_phrase = '(BODY "%s")' % (quoted)
            rs, data = connection.search(None, search_phrase,
                callback=ga.add_loop_cb(_on_search))

        def _on_mailbox_selected(was_changed):
            self.account.connection(callback=ga.add_loop_cb(_on_connection))

        self.select(callback=ga.add_loop_cb(_on_mailbox_selected))

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
            ga.loop_cb_args(callback, messages)

        def _on_search((response, cb_arg, error)):
            typ, data = response
            if typ != "OK":
                ga.loop_cb_args(callback, None)

            ids = string.split(data[0])
            ids_to_fetch = page_from_list(ids, limit, offset)
            self.messages_by_id(ids_to_fetch, only_uids=only_uids,
                callback=ga.add_loop_cb(_on_messages_by_id))

        def _on_connection(connection):
            connection.search(None, 'ALL', callback=ga.add_loop_cb(_on_search))

        def _on_select_complete(result):
            self.account.connection(callback=ga.add_loop_cb(_on_connection))

        self.select(callback=ga.add_loop_cb(_on_select_complete))

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
        def _on_fetch((response, cb_arg, error)):
            typ, data = response
            if typ != "OK" or not data:
                ga.loop_cb_args(callback, None)
            else:
                messages = []
                for msg_parts in data[::-1]:
                    if len(msg_parts) > 1:
                        messages.append(gm.Message(msg_parts, self, full_body=include_body))
                ga.loop_cb_args(callback, messages)

        def _on_connection(connection):
            if include_body:
                request = '(RFC822)'
            else:
                request = '(X-GM-MSGID UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'
            connection.uid("FETCH", ",".join(uids), request,
                callback=ga.add_loop_cb(_on_fetch))

        def _on_select(result):
            self.account.connection(callback=ga.add_loop_cb(_on_connection))

        self.select(callback=ga.add_loop_cb(_on_select))

    def fetch(self, uid, callback=None, include_body=False):
        """Returns a single message from the mailbox by UID

        Returns a single message object, representing the message in the current
        mailbox with the specific UID

        Arguments:
            uid -- the numeric, unique identifier of the message in the mailbox

        Returns:
            A pygmail.message.Message object representing the email message, or
            None if none could be found
        """

        def _on_fetch((response, cb_arg, error)):

            typ, data = response
            if typ != "OK" or not data:
                ga.loop_cb_args(callback, None)
            else:
                for msg_parts in data[::-1]:
                    if len(msg_parts) > 1:
                        ga.loop_cb_args(callback,
                            gm.Message(msg_parts, self, full_body=include_body))

        def _on_connection(connection):
            if include_body:
                request = '(RFC822)'
            else:
                request = '(X-GM-MSGID UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'

            connection.uid("FETCH", uid, request,
                callback=ga.add_loop_cb(_on_fetch))

        def _on_select(result):
            self.account.connection(callback=ga.add_loop_cb(_on_connection))

        self.select(callback=ga.add_loop_cb(_on_select))

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
            A list of zero or more message objects (or uids)

        """

        def _on_fetch((response, cb_arg, error)):
            typ, data = response
            if only_uids:
                ga.loop_cb_args(callback, [string.split(elm, " ")[2][:-1] for elm in data])
            else:
                messages = []
                for msg_parts in data[::-1]:
                    if len(msg_parts) > 1:
                        messages.append(gm.Message(msg_parts, self))
                ga.loop_cb_args(callback, messages)

        def _on_connection(connection):
            if only_uids:
                request = '(UID)'
            else:
                request = '(X-GM-MSGID UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM CC TO SUBJECT DATE MESSAGE-ID)])'
            connection.fetch(",".join(ids), request, callback=ga.add_loop_cb(_on_fetch))

        def _on_select(result):
            self.account.connection(callback=ga.add_loop_cb(_on_connection))

        if not ids:
            callback([])

        self.select(callback=ga.add_loop_cb(_on_select))
