"""Identity context.

Phone + OTP authentication, device registry, JWT access + rotating refresh
tokens. Every other context that needs a current user goes through the
dependencies exposed here (`get_current_user` etc.) — nothing reaches into
the user table directly.
"""
