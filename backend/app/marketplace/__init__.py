"""Marketplace context — RFQ + quotes + reservations + sales + reviews.

Session 4 ships the driver side of the RFQ flow only: a registered driver
submits a part search request tied to one of their vehicles. The incoming
feed for businesses, quotes, reservations, sales and reviews land in
sessions 5 and 6. The part_search_requests table already carries enough
shape for session 5 to attach quotes without a schema migration.
"""
