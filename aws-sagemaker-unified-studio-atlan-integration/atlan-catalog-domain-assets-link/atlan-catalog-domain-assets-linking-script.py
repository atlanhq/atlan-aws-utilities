from pyatlan.client.atlan import AtlanClient
from pyatlan.model.assets import Asset, DataDomain, SageMakerUnifiedStudioPublishedAsset, SageMakerUnifiedStudioSubscribedAsset, SageMakerUnifiedStudioProject
from pyatlan.model.fluent_search import FluentSearch
from pyatlan.model.search import Exists
import requests
import os

####################################################################################################################
######################################### Main Program Starts Here #################################################
####################################################################################################################

def main():
    
    ######### Make sure to set the following environment variables #############
    # ATLASN_BASE_URL: The base URL of the Atlan instance
    # ATLASN_API_KEY: The API key for the Atlan instance
    # SMUS_CONNECTION_QUALIFIED_NAME: The qualified name of the AWS SageMaker Unified Studio connection, where the SMUS assets are cataloged
    # Examples:
        # ATLASN_BASE_URL: https://xyz.atlan.com/
        # ATLASN_API_KEY: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        # SMUS_CONNECTION_QUALIFIED_NAME: default/aws-smus/1765552936
    ######### Make sure to set the following environment variables #############
    tenant_name = os.getenv('ATLAN_BASE_URL')
    bearer_token = os.getenv('ATLAN_API_KEY')
    smus_conn_qn = os.getenv(key='SMUS_CONNECTION_QUALIFIED_NAME',default='NONE')
    session = requests.session()
    session.headers.update({"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"})

    #initialize pyAtlan SDK
    client = AtlanClient(base_url=tenant_name, api_key=bearer_token)
    print("SDK Client initialialized for tenant "+tenant_name) 

    #build a domain dict
    print(f"Looking up Domains...")
    domain_info = {}
    domain_search_request = (
        FluentSearch()
        .where(FluentSearch.active_assets())
        .where(FluentSearch.asset_types(one_of=[DataDomain]))
        .include_on_results(DataDomain.PARENT_DOMAIN)
        .include_on_results(DataDomain.PARENT_DOMAIN_QUALIFIED_NAME)
    ).to_request()

    domain_search_results = client.asset.search(domain_search_request)
    for asset in domain_search_results:
        domain_info[asset.name] = asset.guid
    print(f"Domain info lookup complete. Found {len(domain_info.keys())} Domain definitions!!")   

    #lookup project assets with associated domain info
    print(f"Looking up SMUS Assets...")
    search_request = (
        FluentSearch()
        .where(FluentSearch.active_assets())
        .where(FluentSearch.asset_types(one_of=[SageMakerUnifiedStudioProject]))
        .where(Exists(field="__customAttributes"))
        .include_on_results(Asset.CUSTOM_ATTRIBUTES)
        .include_on_results(SageMakerUnifiedStudioProject.SMUS_PUBLISHED_ASSETS)
        .include_on_results(SageMakerUnifiedStudioProject.SMUS_SUBSCRIBED_ASSETS)
    ) 
    if smus_conn_qn != 'None':
        search_request = search_request.where(Asset.CONNECTION_QUALIFIED_NAME.eq(smus_conn_qn))

    #examine and update linked asset domains
    assets_to_update = []
    search_results = client.asset.search(search_request.to_request())
    for asset in search_results:
        print(f"SMUS Project Asset Name: {asset.name}; GUID: {asset.guid}; QN: {asset.qualified_name}; Domain: {asset.domain_g_u_i_ds}")  
        owning_domain_name = f'{asset.custom_attributes['domainUnitName']}'
        owning_domain_guid = f'{domain_info[asset.custom_attributes['domainUnitName']]}'
        #update domain for the project asset
        print(f"-> Accounting for Domain update on the Project asset...")
        asset.domain_g_u_i_ds = [owning_domain_guid]
        assets_to_update.append(asset)
        
        #update domain for all published and subscribed assets associated with the project
        print(f"-> Accounting for Domain update on the constituent Published/Subscribed assets ...")
        published_asset_guids = []
        no_of_published_assets = len(asset.smus_published_assets)
        if no_of_published_assets > 0:
            published_asset_guids = list(map(lambda x: x.guid,asset.smus_published_assets))
        subscribed_asset_guids = []
        no_of_subscribed_assets = len(asset.smus_subscribed_assets)
        if no_of_subscribed_assets > 0:
            subscribed_asset_guids = list(map(lambda x: x.guid,asset.smus_subscribed_assets))
        project_asset_guids = published_asset_guids + subscribed_asset_guids       
        
        #lookup assets
        print(f"->-> Looking up {len(project_asset_guids)} assets associated with the Project...")
        asset_lookup_request = (
            FluentSearch()
            .where(FluentSearch.active_assets())
            .where(FluentSearch.asset_types(one_of=[SageMakerUnifiedStudioPublishedAsset,SageMakerUnifiedStudioSubscribedAsset]))
            .where(Asset.GUID.within(values=project_asset_guids))
        ).to_request()

        asset_lookup_results = client.asset.search(asset_lookup_request)
        for project_asset in asset_lookup_results:
            print(f"->->-> Asset Name: {project_asset.name}; Type: {project_asset.type_name}; GUID: {project_asset.guid}; QN: {project_asset.qualified_name}; Domain: {project_asset.domain_g_u_i_ds}") 
            project_asset.domain_g_u_i_ds = [owning_domain_guid]
            assets_to_update.append(project_asset)

    print(f"Totally {len(assets_to_update)} to enrich...")
    #push enrichment
    for i in range(0,len(assets_to_update),50):
        update_response = client.asset.save(entity=assets_to_update[i:i+50]) 
        if i != 0 and i%50 == 0 and i < len(assets_to_update) -1:
            print(f"{i+50} assets updated...")  
    print(f"Asset enrichment complete!!")    
        

if __name__ == "__main__":
    main()                    