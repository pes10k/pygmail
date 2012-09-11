def quote(param):
    """ Escapes characters in an IMAP parameter

    The IMAP spec requires escaping certain characters from IMAP commands,
    specifically the double-quote and backslash characters.
    See http://tools.ietf.org/html/rfc2683#section-3.4.2 for more
    details

    Argument:
        param -- A parameter of an IMAP command (such as a search term)
                 to sanatize and make safe for inclusion in an IMAP
                 command

    Returns:
        The same parameter, but escaped and safe to include in an IMAP command
    """
    return param.replace("\\", "\\\\").replace(r'"', r"\"")
