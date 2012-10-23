from threading import Thread
from Queue import Queue
from pygmail.account import GmailAccount
import uuid


class ConnectionQueue(object):
    """Manages a thread pool of account connections to GmailAccount

    Some requests (searching, fetching, etc.) can take a while to get responses
    from the GMail server, so, to speed things up, this class manages creating
    multiple connections to the GMail IMAP server, without creating so many that
    Google starts dropping our connecitons.

    This thread pool executes work on a FIFO basis

    """
    def __init__(self, account, num_threads=4):
        """Creates a thread pool of connections identical to the given account

        Named Arguments:
            num_threads -- The maximuim number of threads / simultanious
                           connections to make to GMail.  Since Gmail only
                           allows a maximum of 9, setting this to anything
                           higher will probably cause problems.

        Arguments:
            account -- An initilized, connected GmailAccount object
        """
        email = account.email
        xoauth_string = account.xoauth_string
        oauth2_token = account.oauth2_token
        password = account.password

        print (account.email, account.xoauth_string, account.oauth2_token, account.password)

        self.num_threads = num_threads
        self.identifier = str(uuid.uuid4())
        self.queue = Queue()

        # We lazy load / create the threads, so they're only created the
        # first time we need work done, not when this class is initilzied.
        # This flag just keeps track of whether those threads exist for this
        # queue.
        self.threads_exist = False
        self.connections = []
        for i in range(num_threads):
            account = GmailAccount(email, xoauth_string=xoauth_string,
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
        self.queue.empty()
        for i in range(self.num_threads):
            self.queue.put({"action": "stop"})
        return self

    def work(self, data, work_callback, complete_callback):
        """Beings performing a set of work in the queue

        This method begins performing a set amount of work, in parallel, over
        allocated GMail connections, asyncronously.  The provided callback
        will be called when all work has been completed.

        Arguments:
            data              -- an iterable object, containing chunks of work
                                 to be be performed
            work_callback     -- the function that performs the requested work
                                 on subsets of the above data.  This callback
                                 receives a tuple with the following items:
                                   account  -- an initilized GmailAccount object
                                   sub_data -- one entry from the above provided
                                               data parameter
                                 This function should return a single object
                                 describing the work performed, that will
                                 be provided to the complete_callback
            complete_callback -- A function that will be called when all work
                                 is completed.  It will receive no parameters
        """
        def thread_work(a_queue):
            while True:
                item = a_queue.get()
                if "action" in item:
                    action = item["action"]
                    if action == "stop":
                        a_queue.task_done()
                        return
                    elif action == "do":
                        item["callback"]((item["account"], item["work"], item["index"]))
                        a_queue.task_done()

        if self.threads_exist is False:
            for i in range(self.num_threads):
                t = Thread(target=thread_work, args=(self.queue,))
                t.daemon = True
                t.start()

        for index, some_work in enumerate(data):
            self.queue.put({"action": "do", "callback": work_callback,
                "work": some_work, "account": self.connections[int(index % self.num_threads)],
                "index": index})
        self.queue.join()
        complete_callback()
