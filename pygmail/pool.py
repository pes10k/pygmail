from multiprocessing import Pool
import uuid


class ConnectionPool(object):
    """Manages a thread pool of account connections to GmailAccount

    Some requests (searching, fetching, etc.) can take a while to get responses
    from the GMail server, so, to speed things up, this class manages creating
    multiple connections to the GMail IMAP server, without creating so many that
    Google starts dropping our connecitons.

    This thread pool executes work on a FIFO basis

    """
    def __init__(self, email, num=8, oauth2_token=None):
        """Creates a thread pool of connections to Gmail

        Named Arguments:
            num            -- The maximuim number of simultanious
                              connections to make to GMail.  Since Gmail only
                              allows a maximum of 9, setting this to anything
                              higher will probably cause problems.
            oauth2_token   -- An OAuth2 access token for use when connecting
                              with the given email address (default: None)

        Arguments:
            email -- The email address of the account being connected to
        """
        self.num_processes = num
        self.identifier = str(uuid.uuid4())
        self.email = email
        self.oauth2_token = oauth2_token

        # We lazy load / create the threads, so they're only created the
        # first time we need work done, not when this class is initilzied.
        # This flag just keeps track of whether those threads exist for this
        # queue.
        self.pool = Pool(processes=num)

    def __del__(self):
        """Make sure that we close open connections before we destroy the object"""
        self.end()

    def end(self):
        """Empties all work queued up in the thread pool

        We empty and kill to pool by first clearing all items out of the queue,
        and then pushing in a few more items, each of which with "instructions"
        to end the thread.

        Return:
            A reference to the current object
        """
        self.pool.terminate()
        return self

    def call(self, work_callback, complete_callback):
        """Adds a callback to issue on the first available account in the pool

        This is equivilent to calling work() below with None as the data
        argument

        Arguments:
            work_callback -- A function that performs a request using a Gmail
                             account object.  This function should take
                             a single argument, a pygmail.account.Account
                             instance
        """
        self.work((None,), work_callback, complete_callback)

    def work(self, data, work_callback, complete_callback):
        """Beings performing a set of work in the queue

        This method begins performing a set amount of work, in parallel, over
        allocated GMail connections, asyncronously.  The provided callback
        will be called when all work has been completed.

        Arguments:
            data              -- an iterable object, containing chunks of work
                                 to be be performed.  If None, the work_callback
                                 function will be called once
            work_callback     -- the function that performs the requested work
                                 on subsets of the above data.  This callback
                                 receives a tuple with the following items:
                                   account  -- an initilized pygmail.account.
                                               Account object
                                   sub_data -- one entry from the above provided
                                               data parameter
                                 This function should return a single object
                                 describing the work performed, that will
                                 be provided to the complete_callback
            complete_callback -- A function that will be called when all work
                                 is completed.  It will receive no parameters
        """

        # Clear up any previous work that is still in a thread, so we only
        # add work to an empty pool
        self.pool = Pool(processes=self.num_processes)
        work = list([(self.email, self.oauth2_token, work) for work in data])
        rs = self.pool.map_async(work_callback, work, callback=complete_callback)
        self.pool.close()
