from threading import Thread
from Queue import Queue
from pygmail.account import Account
import uuid
import threading


class ConnectionPool(object):
    """Manages a thread pool of account connections to GmailAccount

    Some requests (searching, fetching, etc.) can take a while to get responses
    from the GMail server, so, to speed things up, this class manages creating
    multiple connections to the GMail IMAP server, without creating so many that
    Google starts dropping our connecitons.

    This thread pool executes work on a FIFO basis

    """
    def __init__(self, email, num_threads=4, xoauth_string=None,
        password=None, oauth2_token=None):
        """Creates a thread pool of connections to Gmail

        Named Arguments:
            num_threads    -- The maximuim number of threads / simultanious
                              connections to make to GMail.  Since Gmail only
                              allows a maximum of 9, setting this to anything
                              higher will probably cause problems.
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
        self.num_threads = num_threads
        self.identifier = str(uuid.uuid4())
        self.queue = Queue()

        # Lock for keeping threadsafe the count of the number of bins of data
        # that have been processed when in a pool of work
        self.lock = threading.Lock()

        # Syncronized count of the number of bins of work that have been
        # processed
        self.complete_count = 0

        # The number of work items currently in the queue to be processed
        self.work_count = 0

        # We lazy load / create the threads, so they're only created the
        # first time we need work done, not when this class is initilzied.
        # This flag just keeps track of whether those threads exist for this
        # queue.
        self.threads_exist = False
        self.connections = []
        for i in range(num_threads):
            account = Account(email, xoauth_string=xoauth_string,
                password=password, oauth2_token=oauth2_token)
            account.connection()
            self.connections.append(account)

    def __del__(self):
        """Make sure that we close open connections before we destroy the object"""
        for account in self.connections:
            account.close()
        self.end()

    def end(self):
        """Empties all work queued up in the thread pool

        We empty and kill to pool by first clearing all items out of the queue,
        and then pushing in a few more items, each of which with "instructions"
        to end the thread.

        Return:
            A reference to the current object
        """
        try:
            self.lock.release()
        except:
            ""
        if self.threads_exist:
            for i in range(self.num_threads):
                self.queue.put({"action": "stop"})
            self.queue.join()
        self.threads_exist = False
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
        self.work(None, work_callback, complete_callback)

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
        self.end()

        def thread_work(a_queue):
            while True:
                item = a_queue.get()
                if "action" in item:
                    action = item["action"]
                    if action == "stop":
                        a_queue.task_done()
                        return
                    elif action == "do_single":
                        response = item["callback"](item["account"])
                    elif action == "do":
                        item["work_container"][item["index"]] = item["callback"]((item["account"], item["work"]))

                    self.lock.acquire()
                    self.complete_count += 1
                    a_queue.task_done()
                    self.lock.release()

                    print "Completed round %d of %d" % (self.complete_count, self.work_count)

                    if self.complete_count == self.work_count:
                        if action == "do_single":
                            item["complete_callback"](response)
                        elif action == "do":
                            item["complete_callback"](item["work_container"])

        if self.threads_exist is False:
            for i in range(self.num_threads):
                t = Thread(target=thread_work, args=(self.queue,))
                t.daemon = True
                t.start()

        self.complete_count = 0

        if data is None:
            self.work_count = 1
            self.queue.put({
                "action": "do_single",
                "callback": work_callback,
                "complete_callback": complete_callback,
                "account": self.connections[0],
                "work": None,
            })
        else:
            self.work_count = len(data)
            work_container = [None] * self.work_count
            for index, some_work in enumerate(data):
                self.queue.put({
                    "action": "do",
                    "callback": work_callback,
                    "complete_callback": complete_callback,
                    "account": self.connections[int(index % self.num_threads)],
                    "work": some_work,
                    "index": index,
                    "work_container": work_container
                })
