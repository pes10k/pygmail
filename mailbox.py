import re
import string
import message as gm


def page_from_list(a_list, limit, offset):
    """ Retreives the paginated section from the provided list

    Helps pagination needs by extracting only the section of the given list
    described by the limit and offset parameters w/o causing invalid index
    errors.

    Args:
        a_list -- A list of any length
        limit  -- The maximum number of elements to return from the list
        offset -- The index of the first element in the list to return

    Return:
        A slice from the given list with at most "limit" elements

    """
    count = len(a_list)
    # If the given offset is greater than the total number
    # of messages in the inbox, there are no messages to return
    if count <= offset:
        return []
    else:
        first_elm_index = offset

    last_req_item = offset + limit
    last_elm_index = count if last_req_item >= count else last_req_item
    return a_list[first_elm_index:last_elm_index]


class GmailMailbox(object):
    """Represents a single mailbox within a gmail account

    Instances of this class are not intended to be initilized directly, but
    instead managed by a gmail.GmailAccount Instances

    """

    # Classwide regular expression used to extract the human readable versions
    # of the mailbox names from the full, IMAP versions
    NAME_PATTERN = re.compile(r'\((.*?)\) "(.*)" (.*)')

    # Classwide, simple regular expression to only digits in a string
    COUNT_PATTERN = re.compile(r'[^0-9]')

    def __init__(self, account, full_name):
        """ Initilizes a mailbox object

        Args:
            account      -- An initilized GmailAccount object, which represents
                            the gmail account this mailbox exists in
            mailbox_name -- The full name of the mailbox, in IMAP format, not
                            in easy, human readable format

        """
        self.account = account
        self.connection = account.connection()
        self.full_name = full_name
        self.name = GmailMailbox.NAME_PATTERN.match(full_name).groups()[2]

    def __str__(self):
        return self.name

    def count(self):
        """ Returns a count of the number of emails in the mailbox

        Returns:
            The int value of the number of emails in the mailbox, or None on
            error

        """
        rs, data = self.connection.select(self.name)
        if rs == "OK":
            self.account.last_viewed_mailbox = self
            return GmailMailbox.COUNT_PATTERN.sub("", str(data))
        else:
            return None

    def select(self):
        """ Sets this mailbox as the current active one on the IMAP connection

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

    def search(self, term, limit=100, offset=0):
        """ Searches for messages in the inbox that contain a given phrase

        Seaches for a given phrase in the current mailbox, and returns a list
        of messages that have the phrase in the HTML and/or plain text part
        of their body

        Args:
            term -- the search term to search for in the current mailbox

        Keyword arguments:
            limit  -- The maximum number of messages to return
            offset -- The first message to return out of the entire set of
                      messages in the inbox

        Returns:
            A two index tupple.  The element in the first index is a
            list of zero or more GmailMessage objects, or None if no
            information could be found about the mailbox.  The second element
            is the total number of messages (not just those returned from the
            limit-offset parameters)

        """
        self.select()
        rs, data = self.connection.search(None, '(BODY "%s")' % (term))
        if rs != "OK":
            return None

        ids = string.split(data[0])
        ids_to_fetch = page_from_list(ids, limit, offset)
        return self.messages_by_id(ids_to_fetch), len(ids)

    def messages(self, limit=100, offset=0):
        """ Returns a list of all the messages in the inbox

        Fetches a list of all messages in the inbox.  This list is by default
        limited to only the first 100 results, though pagination can trivially
        be implemented using the limit / offset parameters

        Keyword arguments:
            limit  -- The maximum number of messages to return
            offset -- The first message to return out of the entire set of
                      messages in the inbox

        Return:
            A two index tupple.  The element in the first index is a
            list of zero or more GmailMessage objects, or None if no
            information could be found about the mailbox.  The second element
            is the total number of messages (not just those returned from the
            limit-offset parameters)

        """
        self.select()
        rs, data = self.connection.search(None, 'ALL')
        if rs != "OK":
            return None

        ids = string.split(data[0])
        ids_to_fetch = page_from_list(ids, limit, offset)
        return self.messages_by_id(ids_to_fetch), len(ids)

    def messages_by_id(self, ids):
        """ Fetches messages in the mailbox by their id

        Returns a list of all messages in the current mailbox that match
        any of the provided ids.

        Args:
            ids -- A list of zero or more email ids, which should match
                   messages in the current mailbox

        Returns:
            A list of zero or more message objects

        """
        self.select()
        request = '(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
        fetch_rs, fetch_data = self.connection.fetch(",".join(ids), request)

        messages = []
        for msg_parts in fetch_data[::-1]:
            if len(msg_parts) > 1:
                messages.append(gm.GmailMessage(msg_parts, self))
        return messages
