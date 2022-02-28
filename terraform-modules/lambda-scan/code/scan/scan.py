#!/usr/bin/env python
import json

from utils.utils_aws import (
    list_hosted_zones,
    list_resource_record_sets,
    publish_to_sns,
    get_cloudfront_origin,
    list_domains,
)
from utils.utils_dns import vulnerable_ns, vulnerable_cname, vulnerable_alias
from utils.utils_db import db_vulnerability_found, db_get_unfixed_vulnerability_found_date_time
from utils.utils_requests import vulnerable_storage


def process_vulnerability(domain, account_name, resource_type, vulnerability_type, takeover=""):

    # check if vulnerability has already been identified
    if db_get_unfixed_vulnerability_found_date_time(domain):
        print(f"{domain} in {account_name} is still vulnerable")

    # if it's a new vulnerability, add to JSON and write to DynamoDB
    else:
        print(f"New vulnerability {domain} in {account_name}")
        vulnerable_domains.append(domain)

        if account_name == "Cloudflare":
            cloud = "Cloudflare"
        else:
            cloud = "AWS"

        if takeover:
            json_data["New"].append(
                {
                    "Account": account_name,
                    "Cloud": cloud,
                    "Domain": domain,
                    "ResourceType": resource_type,
                    "VulnerabilityType": vulnerability_type,
                    "Takeover": takeover,
                }
            )

        else:
            json_data["New"].append(
                {
                    "Account": account_name,
                    "Cloud": cloud,
                    "Domain": domain,
                    "ResourceType": resource_type,
                    "VulnerabilityType": vulnerability_type,
                }
            )

        db_vulnerability_found(domain, account_name, vulnerability_type, resource_type)


def alias_cloudfront_s3(account_name, record_sets, account_id):

    record_sets_filtered = [
        r
        for r in record_sets
        if "AliasTarget" in r and "cloudfront.net" in r["AliasTarget"]["DNSName"] and "AAAA" not in r["Type"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_storage(domain)
        if result:
            takeover = get_cloudfront_origin(account_id, account_name, record["AliasTarget"]["DNSName"])
            process_vulnerability(domain, account_name, "CloudFront S3", "Alias", takeover)


def alias_eb(account_name, record_sets):

    record_sets_filtered = [
        r for r in record_sets if "AliasTarget" in r and "elasticbeanstalk.com" in r["AliasTarget"]["DNSName"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_alias(domain)
        if result:
            takeover = record["AliasTarget"]["DNSName"]
            process_vulnerability(domain, account_name, "Elastic Beanstalk", "Alias", takeover)


def alias_s3(account_name, record_sets):

    record_sets_filtered = [
        r
        for r in record_sets
        if "AliasTarget" in r
        if ("amazonaws.com" in r["AliasTarget"]["DNSName"]) and "s3-website" in (r["AliasTarget"]["DNSName"])
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_storage(domain, https=False)
        if result:
            takeover = domain + "s3-website." + record["AliasTarget"]["DNSName"].split("-", 2)[2]
            process_vulnerability(domain, account_name, "S3", "Alias", takeover)


def cname_azure(account_name, record_sets):

    vulnerability_list = ["azure", ".cloudapp.net", "core.windows.net", "trafficmanager.net"]

    record_sets_filtered = [
        r
        for r in record_sets
        if r["Type"] in ["CNAME"]
        and any(vulnerability in r["ResourceRecords"][0]["Value"] for vulnerability in vulnerability_list)
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_cname(domain)
        if result:
            process_vulnerability(domain, account_name, "Azure", "CNAME")


def cname_cloudfront_s3(account_name, record_sets, account_id):

    record_sets_filtered = [
        r for r in record_sets if r["Type"] == "CNAME" and "cloudfront.net" in r["ResourceRecords"][0]["Value"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_storage(domain)
        if result:
            takeover = get_cloudfront_origin(account_id, account_name, record["ResourceRecords"][0]["Value"])
            process_vulnerability(domain, account_name, "CloudFront S3", "CNAME", takeover)


def cname_eb(account_name, record_sets):

    record_sets_filtered = [
        r for r in record_sets if r["Type"] in ["CNAME"] and "elasticbeanstalk.com" in r["ResourceRecords"][0]["Value"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_cname(domain)
        if result:
            takeover = record["ResourceRecords"][0]["Value"]
            process_vulnerability(domain, account_name, "Elastic Beanstalk", "CNAME", takeover)


def cname_google(account_name, record_sets):

    record_sets_filtered = [
        r
        for r in record_sets
        if r["Type"] in ["CNAME"] and "c.storage.googleapis.com" in r["ResourceRecords"][0]["Value"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_storage(domain, https=False)
        if result:
            takeover = record["ResourceRecords"][0]["Value"]
            process_vulnerability(domain, account_name, "Google cloud storage", "CNAME", takeover)


def cname_s3(account_name, record_sets):

    record_sets_filtered = [
        r
        for r in record_sets
        if r["Type"] in ["CNAME"]
        and "amazonaws.com" in r["ResourceRecords"][0]["Value"]
        and ".s3-website." in r["ResourceRecords"][0]["Value"]
    ]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"checking if {domain} is vulnerable to takeover")
        result = vulnerable_storage(domain, https=False)
        if result:
            takeover = record["ResourceRecords"][0]["Value"]
            process_vulnerability(domain, account_name, "S3", "CNAME", takeover)


def ns_subdomain(account_name, hosted_zone, record_sets):

    record_sets_filtered = [r for r in record_sets if r["Type"] == "NS" and r["Name"] != hosted_zone["Name"]]

    for record in record_sets_filtered:
        domain = record["Name"]
        print(f"testing {domain} in {account_name} account")
        result = vulnerable_ns(domain)
        if result:
            process_vulnerability(domain, account_name, "hosted zone", "NS")


def domain_registrar(account_id, account_name):

    print(f"Searching for registered domains in {account_name} account")
    domains = list_domains(account_id, account_name)

    for domain in domains:
        print(f"testing {domain} in {account_name} account")
        result = vulnerable_ns(domain)
        if result:
            print(f"{domain} in {account_name} is vulnerable")
            process_vulnerability(domain, account_name, "hosted zone", "registered domain")

    if len(domains) == 0:
        print(f"No registered domains found in {account_name} account")


def lambda_handler(event, context):  # pylint:disable=unused-argument

    global vulnerable_domains
    vulnerable_domains = []

    global json_data
    json_data = {"New": []}

    print(f"Input: {event}")

    account_id = event["Id"]
    account_name = event["Name"]

    hosted_zones = list_hosted_zones(event)

    for hosted_zone in hosted_zones:
        print(f"Searching for vulnerable domain records in hosted zone {hosted_zone['Name']}")

        record_sets = list_resource_record_sets(account_id, account_name, hosted_zone["Id"])

        alias_cloudfront_s3(account_name, record_sets, account_id)
        alias_eb(account_name, record_sets)
        alias_s3(account_name, record_sets)
        cname_azure(account_name, record_sets)
        cname_cloudfront_s3(account_name, record_sets, account_id)
        cname_eb(account_name, record_sets)
        cname_google(account_name, record_sets)
        cname_s3(account_name, record_sets)
        ns_subdomain(account_name, hosted_zone, record_sets)

    if len(hosted_zones) == 0:
        print(f"No hosted zones found in {account_name} account")

    domain_registrar(account_id, account_name)

    print(json.dumps(json_data, sort_keys=True, indent=2))

    if len(vulnerable_domains) > 0:
        publish_to_sns(json_data, "New domains vulnerable to takeover")