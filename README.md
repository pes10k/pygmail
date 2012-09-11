pyGmail
===

Description
---
A python module for interacting with gmail accounts via user/pass or [XOAuth](https://sites.google.com/site/oauthgoog/Home/oauthimap)

Usage
---
Here is a sample listing of how to access the messages in a gmail account and delete
a message:

    gmail_account = "example@gmail.com"
    gmail_password = "examplepw"
    account = GMAccount.GmailAccount(gmail_account, password=gmail_password)

    print "Account includes the following mailboxes:"

    mailboxes = account.mailboxes()
    for mailbox in mailboxes:
        print " - %s (%d messages)" % (mailbox.name, mailbox.count())

    print "The first mailbox contains the following messages:"
    messages, num_messages = mailboxes[0].messages();
    for message in messages:
        print " - subject: %s, from: %s, sent on %s" % (message.subject, message.sender, message.date)

Author
---
Written by Peter Snyder <snyderp@gmail.com> for Professor Chris Kanich in the BITS lab
at the University of Illinois in Chicago
