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


class BrewNVRNotFound(ArtBotExceptions):
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
    """Exception raised if GitHub repo could not be found from the distgit name"""
    pass


class DistgitFromGithubNotFound(ArtBotExceptions):
    """Exception raised if Distgit repo could not be found from the GitHub repo name"""
    pass


class MultipleCdnToBrewMappings(ArtBotExceptions):
    """Exception raised if more than one Brew packages are found for a CDN repo"""
    pass


class BrewNotFoundFromCdnApi(ArtBotExceptions):
    """Exception raised when the json file returned from the CDN repos API does not have Brew packages listed"""
    pass


class BrewFromDeliveryNotFound(ArtBotExceptions):
    """Exception raised when the brew name could not be retrieved from pyxis"""
    pass


class MultipleBrewFromDelivery(ArtBotExceptions):
    """Exception raised if more than one delivery to brew mappings found"""
    pass


class BrewToCdnWithDeliveryNotFound(ArtBotExceptions):
    """Exception raised when we cannot found the CDN repo name using the Brew name that we got using the Delivery Repo name"""
    pass


class DistgitFromBrewNotFound(ArtBotExceptions):
    """Exception raised when we cannot find the distgit name from the given brew name"""


class NullDataReturned(ArtBotExceptions):
    """Exception raise when null data (empty dict, list etc.) is returned from any function, which is necessary for other functions"""


class BrewToDistgitMappingNotFound(ArtBotExceptions):
    """Exception raised when no mapping is found between brew and distgit from the yml file from ocp-build-data/images"""


# Other exceptions
class InternalServicesExceptions(Exception):
    """Super class for all exceptions while trying to access internal services"""
    pass


class KojiClientError(InternalServicesExceptions):
    """Exception raised when we cannot connect to brew."""
    pass


class KerberosAuthenticationError(InternalServicesExceptions):
    """Exception raised for Authentication error if keytab or ticket is missing
    """
