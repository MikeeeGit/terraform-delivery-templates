#!/usr/bin/env python3
"""Single entry point for the staged, reviewed disposable Azure teardown."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import three_tier_teardown as tf
import three_tier_cleanup as cluster
import three_tier_retire_backend as backend

ORDER = [
    "Freeze this lab's manual pipelines and retain evidence/operator access.",
    "Plan/apply aks-lab-gateway pprd removal to withdraw WAF traffic.",
    "Run services cleanup for aks01, then aks02, using their verified release bundles.",
    "Plan/apply aks-lab-azure-devops-connections for hub, prd and pprd; retire its bootstrap PAT.",
    "Plan/apply aks-lab-delivery-identities for prd, pprd and hub.",
    "Plan/apply aks-lab-aks pprd, then aks-lab-workload-vault pprd.",
    "Plan/apply aks-lab-routes hub while Firewall and networks still exist.",
    "Unregister the exact private agent, prove independent state access, close management tunnels.",
    "Plan/apply aks-lab-private-worker hub, then aks-lab-firewall hub.",
    "Detach-plan/apply aks-lab-network for hub, pprd and prd while all states exist.",
    "Plan/apply aks-lab-network prd, then pprd, then hub.",
    "Backend-plan migrates the existing bootstrap state locally and plans removal; backend-apply applies its reviewed plan.",
    "Verify the exact owned resource groups and both recorded node resource groups are absent.",
]

def controls(action, arguments):
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--pipeline-id",type=int,action="append")
    p.add_argument("--queue-id",type=int)
    p.add_argument("--agent-id",type=int)
    p.add_argument("--execute",action="store_true")
    a=p.parse_args(arguments);tf.configure(a.config);tf.create_output(a.output)
    # DevOps uses its separately configured CLI login; ARM cleanup keeps the
    # isolated operator profile. No Azure subscription selection is changed.
    env=dict(os.environ)
    env.pop("AZURE_CONFIG_DIR",None)
    def invoke(area, resource, route, method="GET", body=None, query=None):
        args=["az","devops","invoke","--organization",tf.ORGANIZATION,
              "--area",area,"--resource",resource,"--http-method",method,
              "--api-version","7.1","--output","json","--route-parameters"]
        args += [key+"="+str(value) for key,value in route.items()]
        if query:
            args += ["--query-parameters"]+[key+"="+str(value) for key,value in query.items()]
        if body is not None:
            path=a.output/("request-"+str(len(list(a.output.glob("request-*.json"))))+".json")
            tf.write_private(path,json.dumps(body))
            args += ["--in-file",str(path)]
        result=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        tf.require(result.returncode==0,"Azure DevOps control operation failed; retain the worker and inspect the selected project/login")
        return json.loads(result.stdout) if result.stdout.strip() else {}
    if action=="freeze":
        tf.require(a.pipeline_id and len(a.pipeline_id)==len(set(a.pipeline_id))
                   and all(x>0 for x in a.pipeline_id),"Supply each exact lab pipeline ID once")
        outstanding=invoke("build","builds",{"project":tf.PROJECT},query={"statusFilter":"inProgress,notStarted,postponed"})
        tf.require(not outstanding.get("value"),"Lab runs remain active/queued; let them finish or cancel them explicitly before freezing")
        before=[]
        for identifier in a.pipeline_id:
            d=invoke("build","definitions",{"project":tf.PROJECT,"definitionId":identifier})
            tf.require(d["project"]["id"]==tf.PROJECT and d["repository"]["name"].startswith("aks-lab-"),
                       "Pipeline does not belong to this private lab")
            before.append(d)
        tf.write_private(a.output/"pipelines-before.json",json.dumps(before,indent=2))
        if a.execute:
            for d in before:
                route={"project":tf.PROJECT,"definitionId":d["id"]}
                if d.get("queueStatus")!="disabled":
                    changed=dict(d,queueStatus="disabled")
                    invoke("build","definitions",route,"PUT",changed)
                tf.require(invoke("build","definitions",route).get("queueStatus")=="disabled",
                           "Pipeline queue disable was not observed")
        result={"status":"frozen" if a.execute else "inventory-only","pipeline_ids":a.pipeline_id}
    else:
        tf.require(a.queue_id and a.agent_id and a.queue_id>0 and a.agent_id>0,"Supply the exact project queue and agent IDs")
        queue=invoke("distributedtask","queues",{"project":tf.PROJECT,"queueId":a.queue_id})
        tf.require(queue["name"]=="aks-lab-private" and queue.get("pool",{}).get("id"),"Expected this lab's private queue")
        route={"poolId":queue["pool"]["id"],"agentId":a.agent_id}
        agent=invoke("distributedtask","agents",route,query={"includeAssignedRequest":"true"})
        tf.require(agent["name"].startswith("aks-lab-worker-") and not agent.get("assignedRequest"),
                   "Agent ownership is unexpected or it still has an assigned job")
        tf.write_private(a.output/"agent-before.json",json.dumps(agent,indent=2))
        if a.execute:
            invoke("distributedtask","agents",route,"DELETE")
            agents=invoke("distributedtask","agents",{"poolId":queue["pool"]["id"]})
            tf.require(not any(x["id"]==a.agent_id for x in agents.get("value",[])),"Agent registration still exists")
        result={"status":"unregistered" if a.execute else "inventory-only","agent_id":a.agent_id,"pool_id":queue["pool"]["id"]}
    tf.write_private(a.output/"result.json",json.dumps(result,indent=2))
    print(json.dumps(result))

def verify(arguments):
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True,type=Path)
    p.add_argument("--cluster-inventory",required=True,type=Path,action="append")
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(arguments);tf.configure(a.config);tf.create_output(a.output)
    expected=set()
    for name,environments in tf.TARGETS.items():
        for environment in environments: expected |= tf.resource_groups(name,environment)
    expected |= {f"uks-{e}-aks-lab-tfstate-rsg" for e in ("hub","pprd","prd")}
    slots=set()
    for path in a.cluster_inventory:
        row=json.loads(tf.regular(path))
        slot=row["slot"]
        resource=f"/subscriptions/{tf.SUBSCRIPTION}/resourcegroups/uks-pprd-akslab-aks-rg/providers/microsoft.containerservice/managedclusters/uks-pprd-akslab-{slot}"
        tf.require(slot in ("aks01","aks02") and slot not in slots and row["cluster_id"].lower()==resource,
                   "Use one actual pre-removal cluster inventory per selected slot")
        tf.require(row["node_resource_group"].lower().startswith("mc_uks-pprd-akslab-aks-rg_uks-pprd-akslab-"+slot+"_"),
                   "Unexpected managed node resource group")
        expected.add(row["node_resource_group"].lower());slots.add(slot)
    tf.require(slots=={"aks01","aks02"},"Both cluster inventories are required")
    env=tf.child_environment(a.output)
    groups=json.loads(tf.run(["az","group","list","--subscription",tf.SUBSCRIPTION,"-o","json"],
                            a.output,env,"Independent remaining resource-group inventory"))
    remaining=[{"name":g["name"],"id":g["id"]} for g in groups if g["name"].lower() in expected]
    report={"status":"removed" if not remaining else "resources-remain",
            "subscription_id":tf.SUBSCRIPTION,"expected_resource_groups":sorted(expected),
            "remaining_resource_groups":remaining,
            "limits":["Protected soft-deleted Key Vault retention is checked separately.",
                      "Private CI records and off-cloud recovery evidence are intentionally retained.",
                      "Quota, provider registration and the existing administrator group are outside removal scope."]}
    tf.write_private(a.output/"verification.json",json.dumps(report,indent=2))
    tf.require(not remaining,"Owned resource groups remain; inspect verification.json")
    print(json.dumps({"status":"removed","verified_absent_resource_groups":len(expected)}))

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    os.umask(0o077)
    if not args or args[0] in ("list","--help","-h"):
        print(__doc__)
        print("\n".join(f"{i}. {item}" for i,item in enumerate(ORDER,1)))
        print("\nActions: freeze, inventory, plan, detach-plan, apply, services, unregister-agent, backend-plan, backend-apply, verify")
        print("Pass --help after an action to see its exact inputs. No action runs implicitly.")
        return
    action=args.pop(0)
    if action in ("inventory","plan","detach-plan","apply"):
        tf.main(["--mode",action,*args])
    elif action=="services":
        cluster.main(["--phase","services",*args])
    elif action in ("backend-plan","backend-apply"):
        backend.main(["--mode",action.removeprefix("backend-"),*args])
    elif action=="verify":
        verify(args)
    elif action in ("freeze","unregister-agent"):
        controls(action,args)
    else:
        raise ValueError("Unknown action; use list for the ordered removal steps")

if __name__=="__main__":
    try: main()
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as error:
        raise SystemExit("Teardown stopped: "+str(error))
