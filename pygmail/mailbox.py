import re
import string
import message as gm
import utilities as gu


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

    def count(self):
        """Returns a count of the number of emails in the mailbox

        Returns:
            The int value of the number of emails in the mailbox, or None on
            error

        """
        rs, data = self.account.connection().select(self.name)
        if rs == "OK":
            self.account.last_viewed_mailbox = self
            return Mailbox.COUNT_PATTERN.sub("", str(data))
        else:
            return None

    def select(self):
        """Sets this mailbox as the current active one on the IMAP connection

        In order to make sure we don't make many many redundant calls to the
        IMAP server, we allow the account managing object to keep track
        of which mailbox was last set as active.  If the current mailbox is
        active, this method does nothing.

        Returns:
            True if any changes were made, otherwise False

        """
        if self is self.account.last_viewed_mailbox:
            return False
        self.count()
        self.account.last_viewed_mailbox = self
        return True

    def search(self, term, limit=100, offset=0, only_uids=False):
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
            limit  -- The maximum number of messages to return
            offset    -- The first message to return out of the entire set of
                         messages in the inbox
            only_uids -- If True, only the UIDs of the matching messages will
                         be returned, instead of full message headers.

        Returns:
            A two index tupple.  The element in the first index is a
            list of zero or more pygmail.message.Message objects (or uids if
            only_uids is TRUE), or None if no information could be found about
            the mailbox. The second element is the total number of messages (not
            just those returned from the limit-offset parameters)

        """
        self.select()
        quoted = gu.quote(term)
        conn = self.account.connection()
        search_phrase = '(BODY "%s")' % (quoted)
        rs, data = conn.search(None, search_phrase)

        if rs != "OK":
            return None

        ids = string.split(data[0])
        ids_to_fetch = page_from_list(ids, limit, offset)
        message_response = self.messages_by_id(ids_to_fetch, only_uids=only_uids)
        return message_response, len(ids)

    def messages(self, limit=100, offset=0, only_uids=False):
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
        self.select()
        conn = self.account.connection()
        rs, data = conn.search(None, 'ALL')
        if rs != "OK":
            return None

        ids = string.split(data[0])
        ids_to_fetch = page_from_list(ids, limit, offset)
        message_response = self.messages_by_id(ids_to_fetch, only_uids=only_uids)
        return message_response, len(ids)

    def fetch_all(self, uids):
        """Returns a list of messages, each specified by their UID

        Returns zero or more GmailMessage objects, each representing a email
        message in the current mailbox.

        Arguments:
            uids -- A list of zero or more email uids

        Returns:
            Zero or more pygmail.message.Message objects, representing any
            messages that matched a provided uid
        """
        self.select()
        request = '(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
        conn = self.account.connection()
        fetch_rs, fetch_data = conn.uid("FETCH", ",".join(uids), request)

        if fetch_rs != "OK" or not fetch_data:
            return None
        return [gm.Message(msg_parts, self) for msg_parts in fetch_data[::-1] if len(msg_parts) > 1]

    def fetch(self, uid):
        """Returns a single message from the mailbox by UID

        Returns a single message object, representing the message in the current
        mailbox with the specific UID

        Arguments:
            uid -- the numeric, unique identifier of the message in the mailbox

        Returns:
            A pygmail.message.Message object representing the email message, or
            None if none could be found
        """
        self.select()
        request = '(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
        conn = self.account.connection()
        fetch_rs, fetch_data = conn.uid("FETCH", uid, request)

        if fetch_rs != "OK" or not fetch_data:
            return None
        for msg_parts in fetch_data[::-1]:
            if len(msg_parts) > 1:
                return gm.Message(msg_parts, self)

    def messages_by_id(self, ids, only_uids=False):
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
        if not ids:
            return []

        self.select()
        conn = self.account.connection()

        if only_uids:
            request = '(UID)'
        else:
            request = '(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
        fetch_rs, fetch_data = conn.fetch(",".join(ids), request)

        if only_uids:
            return [string.split(elm, " ")[2][:-1] for elm in fetch_data]
        else:
            messages = []
            for msg_parts in fetch_data[::-1]:
                if len(msg_parts) > 1:
                    messages.append(gm.Message(msg_parts, self))
            return messages
