pyGmail
===

Description
---
A python module for reading from and writing to gmail accounts. All operations
can either be called in "standard" blocking mode or in a non-blocking
mode using the [Tornado Web Server](http://www.tornadoweb.org/) IO Loop event
loop.

Requirements
---
 * [Tornado](http://www.tornadoweb.org/) (if you want to use the non-blocking methods)
 * [Google OAuth2 Client](https://developers.google.com/api-client-library/python/guide/aaa_oauth)
 * [imaplib2](https://github.com/bcoe/imaplib2)

Author
---
Written by Peter Snyder <snyderp@gmail.com> for Professor Chris Kanich in the [BITS lab](http://www.cs.uic.edu/Bits/)
at the University of Illinois in Chicago
