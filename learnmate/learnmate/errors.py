"""One error type for everything the user can fix. The API turns it into a friendly JSON message."""


class UserError(Exception):
    def __init__(self, code, message, hint="", status=400):
        super().__init__(message)
        self.code, self.message, self.hint, self.status = code, message, hint, status
