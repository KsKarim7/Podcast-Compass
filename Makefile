# Local Kubernetes with kind. Needs Docker, kind, kubectl and make; on Windows run these
# from WSL or Git Bash. Each image is tagged with the current commit, so deploying a new
# commit is a rolling update.

CLUSTER := podcast-compass
TAG     := $(shell git rev-parse --short HEAD)
IMAGE   := podcast-compass:$(TAG)
LABEL   := app=podcast-compass

.PHONY: up build secret deploy status restart heal logs down

up:  ## Create the cluster
	kind create cluster --config k8s/kind-config.yaml

build:  ## Build the image for the current commit
	docker build -t $(IMAGE) .

secret:  ## Create or update the Secret from .env, which git ignores
	kubectl create secret generic gemini --from-env-file=.env \
		--dry-run=client -o yaml | kubectl apply -f -

deploy: build  ## Load the image into kind, apply the manifests, wait for the rollout
	kind load docker-image $(IMAGE) --name $(CLUSTER)
	sed "s|podcast-compass:local|$(IMAGE)|" k8s/deployment.yaml | kubectl apply -f -
	kubectl apply -f k8s/service.yaml
	kubectl rollout status deployment/podcast-compass --timeout=180s
	@echo "Open http://localhost:8080"

status:  ## Pods, their readiness and restarts, and the Service
	kubectl get deployment,pods -l $(LABEL) -o wide
	kubectl get service podcast-compass

restart:  ## Rolling update without a code change: new pods replace old ones one at a time
	kubectl rollout restart deployment/podcast-compass
	kubectl rollout status deployment/podcast-compass --timeout=180s

heal:  ## Delete one pod and wait for the Deployment to bring the count back to two
	kubectl delete pod $$(kubectl get pods -l $(LABEL) -o jsonpath='{.items[0].metadata.name}')
	kubectl get pods -l $(LABEL)
	kubectl wait deployment/podcast-compass --for=jsonpath='{.status.readyReplicas}'=2 --timeout=120s
	kubectl get pods -l $(LABEL)

logs:  ## Recent logs from every pod
	kubectl logs -l $(LABEL) --tail=50 --prefix

down:  ## Delete the cluster and everything in it
	kind delete cluster --name $(CLUSTER)
