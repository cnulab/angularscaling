import os.path
import torch.nn
from sklearn.metrics import roc_curve, auc
from datasets import ClassifierTrain,ValAndTest
from torch.optim import SGD,Adam
import argparse
from torch.utils.data import DataLoader
from files import Dir
from losses import ECELoss,get_conf,ArcMarginProduct
from utils import *
from backbones import Backbone




def training(args):

    batch_size = args.batch_size
    val_batch_size = args.batch_size

    train_steps=args.train_steps
    backbone=args.backbone
    epochs=args.epochs
    s=args.s
    m=args.m


    save_dir = Dir.mkdir("arcface_" + backbone)
    log_path = os.path.join(save_dir, "train.log")
    logger = get_logger(log_path)

    model = Backbone(backbone=backbone).cuda()

    train_dataset = ClassifierTrain(
        num_pairs=epochs * train_steps * batch_size,
        backbone=backbone,
        images_size=model.imagesize
    )

    choose_dataset = ValAndTest(sample_path="data/FIW/pairs/val_choose.txt",
                                backbone=backbone,
                                images_size=model.imagesize
                                )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, num_workers=2, pin_memory=False)
    val_loader = DataLoader(choose_dataset, batch_size=val_batch_size, num_workers=2, pin_memory=False)


    metric_fc = ArcMarginProduct(model.backbone_feature,571, s=s, m=m).cuda()# 571 is the number of fiw training set families
    if args.optimizer=='sgd':
        optimizer_encoder = SGD( [
         {'params': model.parameters(), 'lr': 1e-4},
            {'params': metric_fc.parameters(), 'lr': 1e-2},
        ], lr=1e-4, momentum=0.9)
    else:
        optimizer_encoder = Adam( [
         {'params': model.parameters(), 'lr': 1e-5},
         {'params': metric_fc.parameters(), 'lr': 1e-1},
        ], lr=1e-5)

    criterion = torch.nn.CrossEntropyLoss().cuda()

    max_acc=0.0

    for epoch_i in range(1,epochs+1):

        logger.info('epoch ' + str(epoch_i ))
        arcface_loss_epoch = []

        model.train()
        for index_i, data in enumerate(train_loader):
            img,labels = data

            em= model(img)

            arcface_pred = metric_fc(em, labels)
            loss=criterion(arcface_pred,labels)

            optimizer_encoder.zero_grad()
            loss.backward()
            optimizer_encoder.step()

            arcface_loss_epoch.append(loss.item())
            if index_i  == train_steps-1:
                break

        use_sample=epoch_i*batch_size*train_steps
        train_dataset.set_bias(use_sample)
        logger.info("arcface_loss:" + "%.6f" % np.mean(arcface_loss_epoch))


        model.eval()
        acc, ece, threshold = val_model(model, val_loader)

        logger.info("acc is %.6f " % acc)
        logger.info("ece is %.6f " % ece)
        logger.info("threshold is %.6f " % threshold)

        if max_acc < acc:
            logger.info("validation acc improve from :" + "%.6f" % max_acc + " to %.6f" % acc)
            max_acc = acc
            save_model(model, os.path.join(save_dir,"arcface_"+backbone+"_best_model.pkl"))
        else:
            logger.info("validation acc did not improve from %.6f" % float(max_acc))

    save_model(model, os.path.join(save_dir, "arcface_"+backbone+"_final_model.pkl"))



def save_model(model, path):
    torch.save(model.encoder.state_dict(), path)


@torch.no_grad()
def val_model(model, val_loader):
    y_true = []
    y_pred = []

    for img1, img2, kin_class,labels in val_loader:
        e1 = model(img1.cuda())
        e2 = model(img2.cuda())

        pred=torch.cosine_similarity(e1, e2, dim=1)

        y_pred.append(pred)
        y_true.append(labels)


    y_true = torch.cat(y_true, dim=0)
    y_pred = torch.cat(y_pred, dim=0)

    fpr, tpr, thresholds_keras = roc_curve(y_true.view(-1).cpu().numpy().tolist(),
                                           y_pred.view(-1).cpu().numpy().tolist())

    maxindex = (tpr - fpr).tolist().index(max(tpr - fpr))
    threshold = thresholds_keras[maxindex]

    acc = ((y_pred >= threshold).float() == y_true).float()
    conf = get_conf(y_pred, threshold)
    ece = ECELoss().cuda()(conf,acc).item()

    return torch.mean(acc).item(),ece,threshold





if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="train_encoder")

    parser.add_argument("--batch_size", type=int, default=50, help="batch size")
    parser.add_argument("--epochs", type=int, default=80, help="epochs number")
    parser.add_argument("--train_steps", type=int, default=50,help="number of iterations per epoch")

    parser.add_argument("--s", default=10.0, type=float)
    parser.add_argument("--m", default=0.40, type=float)

    parser.add_argument("--backbone", type=str,choices=['resnet50','resnet101'], default="resnet101")
    parser.add_argument("--optimizer", type=str, choices=['sgd', 'adam'], default="adam")
    parser.add_argument("--gpu", default="0", type=str, help="gpu id you use")

    args = parser.parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    torch.multiprocessing.set_start_method("spawn")
    set_seed(seed=100)

    training(args)
