class ArtBotExceptions(Exception):
    """Super class for all ART bot exceptions"""
    pass


# Art bot exceptions
class DistgitNotFound(ArtBotExceptions):
    """Exception raised for errors in the input dist-git name."""
    pass


class CdnFromBrewNotFound(ArtBotExceptions):
    """Exception raised if CDN is not found from brew name and variant"""
    pass


class CdnNotFound(ArtBotExceptions):
    """Exception raised if CDN is not found from CDN name"""
    pass


class DeliveryRepoNotFound(ArtBotExceptions):
    """Exception raised if delivery repo not found"""
    pass


class BrewIdNotFound(ArtBotExceptions):
    """Exception raised if brew id not found for the given brew package name"""
    pass


class VariantIdNotFound(ArtBotExceptions):
    """Exception raised if variant id not found for a CDN repo"""
    pass


class CdnIdNotFound(ArtBotExceptions):
    """Exception raised if CDN id not found for a CDN repo"""
    pass


class ProductIdNotFound(ArtBotExceptions):
    """Exception raised if Product id not found for a product variant"""
    pass


class DeliveryRepoUrlNotFound(ArtBotExceptions):
    """Exception raised if delivery repo not found on Pyxis."""
    pass


class DeliveryRepoIDNotFound(ArtBotExceptions):
    """Exception raised if delivery repo ID not found on Pyxis."""
    pass


class GithubFromDistgitNotFound(ArtBotExceptions):
    """Exception raised if Github repo could not be found from the distgit name"""
    pass


# Other exceptions
class KojiClientError(Exception):
    """Exception raised when we cannot connect to brew."""
    pass


class KerberosAuthenticationError(Exception):
    """Exception raised for Authentication error if keytab or ticket is missing
    """